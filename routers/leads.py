"""
Core lead routes - handles lead CRUD operations, listing, and bulk actions.
"""

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, cast, String, and_, exists, update

from db import get_db
from models import (
    BusinessLead,
    LeadProperty,
    LeadStatus,
    LeadContact,
    ContactChannel,
    OwnerType,
    BusinessOwnerStatus,
    OwnerSize,
    IndividualOwnerStatus,
    ContactType,
    LeadJourney,
    PrintLog,
)
from typing import Any
from services.property_service import (
    get_available_years,
    get_property_table_for_year,
    get_property_by_id,
    get_property_details_for_lead,
    mark_property_assigned,
    unmark_property_if_unused,
    build_gpt_payload,
    DEFAULT_YEAR,
    PROPERTY_MIN_AMOUNT,
)
from services.journey_service import initialize_lead_journey, get_journey_data
from utils import (
    get_lead_or_404,
    is_lead_editable,
    normalize_owner_fields,
    format_currency,
    prepare_script_content,
    get_next_attempt_number,
)
from helpers.filter_helpers import build_lead_filters, build_filter_query_string, lead_navigation_info
from helpers.phone_scripts import load_phone_scripts, get_phone_scripts_json
from helpers.print_log_helpers import get_print_logs_for_lead, serialize_print_log
from helpers.property_helpers import get_primary_property
from services.gpt_service import fetch_entity_intelligence, GPTConfigError, GPTServiceError
from fastapi.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates

# Import shared templates from main to ensure filters are registered
# This will be set by main.py after filters are registered
templates = None  # Will be set by main.py
PAGE_SIZE = 20

PHONE_SCRIPTS = load_phone_scripts()
PHONE_SCRIPTS_JSON = get_phone_scripts_json()

def _build_phone_script_context(
    owner_name: str | None,
    property_id: str | None,
    property_amount,
    property_details: dict | None,
):
    amount_value = None
    if property_details and property_details.get("propertyamount") not in (None, ""):
        amount_value = property_details.get("propertyamount")
    elif property_amount not in (None, ""):
        amount_value = property_amount

    formatted_amount = format_currency(amount_value) if amount_value not in (None, "") else ""

    return {
        "OwnerName": owner_name or "",
        "PropertyID": property_id or "",
        "PropertyAmount": formatted_amount,
        "PropertyAmountValue": str(amount_value) if amount_value not in (None, "") else "",
        "HolderName": (property_details.get("holdername") if property_details else "") or "",
        "ReportYear": (property_details.get("reportyear") if property_details else "") or "",
        "PropertyType": (property_details.get("propertytypedescription") if property_details else "") or "",
    }

router = APIRouter()


@router.get("/leads/new_from_property", response_class=HTMLResponse)
def new_lead_from_property(
    request: Request,
    property_id: str,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    if not property_id:
        raise HTTPException(status_code=400, detail="property_id query parameter is required")

    if not year:
        year = DEFAULT_YEAR

    prop = get_property_by_id(db, property_id, year)
    if not prop:
        raise HTTPException(status_code=404, detail=f"Property '{property_id}' not found in view")

    if prop.get("assigned_to_lead"):
        # Check if property is already assigned to a lead via LeadProperty
        existing_property = db.scalar(
            select(LeadProperty).where(
                LeadProperty.property_raw_hash == prop["raw_hash"]
            )
        )
        if existing_property:
            return RedirectResponse(
                url=f"/leads/{existing_property.lead_id}/edit",
                status_code=303,
            )
        raise HTTPException(
            status_code=400,
            detail="This property is already linked to an existing lead.",
        )

    phone_script_context = _build_phone_script_context(
        prop.get("ownername") if prop else None,
        prop.get("propertyid") if prop else None,
        prop.get("propertyamount") if prop else None,
        prop,
    )
    
    # Fetch related properties for auto-suggestion
    from services.property_service import find_related_properties_by_owner_name
    related_props = find_related_properties_by_owner_name(
        db,
        prop.get("ownername") or "",
        exclude_lead_id=None
    )
    
    # Format related properties for template
    related_properties_list = []
    for rp in related_props:
        # Exclude the current property and already assigned ones
        if rp.get("raw_hash") != prop.get("raw_hash"):
            already_assigned = db.scalar(
                select(LeadProperty).where(LeadProperty.property_raw_hash == rp.get("raw_hash"))
            ) is not None
            if not already_assigned:
                # Convert Decimal to float for JSON serialization
                property_amount = rp.get("propertyamount")
                if property_amount is not None:
                    if isinstance(property_amount, Decimal):
                        property_amount = float(property_amount)
                    elif property_amount is not None:
                        try:
                            property_amount = float(property_amount)
                        except (TypeError, ValueError):
                            property_amount = None
                else:
                    property_amount = None
                
                related_properties_list.append({
                    "property_id": rp.get("propertyid") or "",
                    "property_raw_hash": rp.get("raw_hash") or "",
                    "property_amount": property_amount,
                    "holder_name": rp.get("holdername") or "",
                    "owner_name": rp.get("ownername") or "",
                })

    return templates.TemplateResponse(
        "lead_form.html",
        {
            "request": request,
            "lead": None,
            "mode": "create",
            "property_id": prop["propertyid"],
            "owner_name": prop["ownername"],
            "property_amount": prop["propertyamount"],
            "related_properties": related_properties_list,
            "statuses": list(LeadStatus),
            "contacts": [],
            "attempts": [],
            "channels": list(ContactChannel),
            "comments": [],
            "owner_types": list(OwnerType),
            "business_owner_statuses": list(BusinessOwnerStatus),
            "owner_sizes": list(OwnerSize),
            "individual_owner_statuses": list(IndividualOwnerStatus),
            "contact_types": list(ContactType),
            "owner_type": OwnerType.business,
            "business_owner_status": BusinessOwnerStatus.active,
            "owner_size": OwnerSize.corporate,
            "individual_owner_status": IndividualOwnerStatus.alive,
            "new_business_name": "",
            "contact_edit_target": None,
            "property_raw_hash": prop.get("raw_hash"),
            "can_generate_letters": False,
            "phone_scripts": PHONE_SCRIPTS,
            "phone_scripts_json": PHONE_SCRIPTS_JSON,
            "phone_script_context_json": json.dumps(phone_script_context, default=str),
            "print_logs_json": json.dumps([], default=str),
        },
    )


@router.post("/leads/create")
def create_lead(
    property_id: str = Form(...),
    owner_name: str = Form(...),
    property_amount: float | None = Form(None),
    property_raw_hash: str | None = Form(None),
    additional_properties: str | None = Form(None),  # JSON array of additional property data
    status: LeadStatus = Form(LeadStatus.new),
    notes: str | None = Form(None),
    owner_type: OwnerType = Form(OwnerType.business),
    business_owner_status: BusinessOwnerStatus | None = Form(None),
    owner_size: OwnerSize | None = Form(None),
    new_business_name: str | None = Form(None),
    individual_owner_status: IndividualOwnerStatus | None = Form(None),
    db: Session = Depends(get_db),
):
    normalized = normalize_owner_fields(
        owner_type, business_owner_status, owner_size, new_business_name,
        individual_owner_status, validate=True
    )

    # Create lead without property fields
    lead = BusinessLead(
        owner_name=owner_name,
        status=status,
        notes=notes,
        owner_type=owner_type,
        business_owner_status=normalized["business_owner_status"],
        owner_size=normalized["owner_size"],
        new_business_name=normalized["new_business_name"],
        individual_owner_status=normalized["individual_owner_status"],
    )
    db.add(lead)
    db.flush()  # Get lead.id
    
    # Create primary property
    if property_raw_hash:
        primary_property = LeadProperty(
            lead_id=lead.id,
            property_id=property_id,
            property_raw_hash=property_raw_hash,
            property_amount=property_amount,
            is_primary=True,
        )
        db.add(primary_property)
        mark_property_assigned(db, property_raw_hash, property_id)
    
    # Add additional properties if provided
    if additional_properties:
        try:
            additional_props_data = json.loads(additional_properties)
            if isinstance(additional_props_data, list):
                for prop_data in additional_props_data:
                    add_prop_id = prop_data.get("property_id")
                    add_prop_hash = prop_data.get("property_raw_hash")
                    add_prop_amount = prop_data.get("property_amount")
                    
                    if add_prop_id and add_prop_hash:
                        # Check if already assigned
                        existing = db.scalar(
                            select(LeadProperty).where(LeadProperty.property_raw_hash == add_prop_hash)
                        )
                        if not existing:
                            additional_property = LeadProperty(
                                lead_id=lead.id,
                                property_id=add_prop_id,
                                property_raw_hash=add_prop_hash,
                                property_amount=add_prop_amount,
                                is_primary=False,
                            )
                            db.add(additional_property)
                            mark_property_assigned(db, add_prop_hash, add_prop_id)
        except (json.JSONDecodeError, TypeError):
            # Ignore invalid JSON, just create with primary property
            pass
    
    db.commit()
    db.refresh(lead)
    
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)


@router.get("/leads", response_class=HTMLResponse)
def list_leads(
    request: Request,
    page: int = 1,
    q: str | None = None,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    attempt_type: str | None = Query(None, description="Type: all, email, phone, mail"),
    attempt_operator: str | None = Query(None, description="Operator: >=, =, <="),
    attempt_count: str | None = Query(None, description="Count number"),
    print_log_operator: str | None = Query(None, description="Operator: >=, =, <="),
    print_log_count: str | None = Query(None, description="Count number"),
    print_log_mailed: str | None = Query(None, description="Mailed status: all, mailed, not_mailed"),
    scheduled_email_operator: str | None = Query(None, description="Operator: >=, =, <="),
    scheduled_email_count: str | None = Query(None, description="Count number"),
    failed_email_operator: str | None = Query(None, description="Operator: >=, =, <="),
    failed_email_count: str | None = Query(None, description="Count number"),
    status: str | None = Query(None, description="Lead status"),
    db: Session = Depends(get_db),
):
    def parse_count(value: str | None) -> int | None:
        if value is None or value == "" or (isinstance(value, str) and value.strip() == ""):
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    
    attempt_type = attempt_type.strip() if attempt_type and isinstance(attempt_type, str) and attempt_type.strip() else None
    attempt_operator = attempt_operator.strip() if attempt_operator and isinstance(attempt_operator, str) and attempt_operator.strip() else None
    print_log_operator = print_log_operator.strip() if print_log_operator and isinstance(print_log_operator, str) and print_log_operator.strip() else None
    print_log_mailed = print_log_mailed.strip() if print_log_mailed and isinstance(print_log_mailed, str) and print_log_mailed.strip() else None
    scheduled_email_operator = scheduled_email_operator.strip() if scheduled_email_operator and isinstance(scheduled_email_operator, str) and scheduled_email_operator.strip() else None
    failed_email_operator = failed_email_operator.strip() if failed_email_operator and isinstance(failed_email_operator, str) and failed_email_operator.strip() else None
    status = status.strip() if status and isinstance(status, str) and status.strip() else None
    
    attempt_count_int = parse_count(attempt_count)
    print_log_count_int = parse_count(print_log_count)
    scheduled_email_count_int = parse_count(scheduled_email_count)
    failed_email_count_int = parse_count(failed_email_count)
    
    if page < 1:
        page = 1

    stmt = select(BusinessLead)
    count_stmt = select(func.count()).select_from(BusinessLead)

    prop_table = get_property_table_for_year(year)
    # Filter leads that have properties matching the year's property table
    year_filter = exists(
        select(1)
        .select_from(LeadProperty)
        .where(LeadProperty.lead_id == BusinessLead.id)
        .where(
            or_(
                exists(
                    select(1)
                    .select_from(prop_table)
                    .where(prop_table.c.row_hash == LeadProperty.property_raw_hash)
                    .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
                ),
                exists(
                    select(1)
                    .select_from(prop_table)
                    .where(cast(prop_table.c.propertyid, String) == LeadProperty.property_id)
                    .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
                )
            )
        )
    )

    filters = build_lead_filters(
        q, attempt_type, attempt_operator, attempt_count_int,
        print_log_operator, print_log_count_int, print_log_mailed,
        scheduled_email_operator, scheduled_email_count_int,
        failed_email_operator, failed_email_count_int, status
    )
    
    filters.append(year_filter)
    
    if filters:
        combined_filter = and_(*filters)
        stmt = stmt.where(combined_filter)
        count_stmt = count_stmt.where(combined_filter)

    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(BusinessLead.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    leads = db.scalars(stmt).all()

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1

    # Get primary property for each lead
    leads_with_data = []
    for lead in leads:
        primary_prop = get_primary_property(lead)
        leads_with_data.append((lead, is_lead_editable(lead), primary_prop))

    return templates.TemplateResponse(
        "leads.html",
        {
            "request": request,
            "leads_with_data": leads_with_data,
            "page": page,
            "total_pages": total_pages,
            "q": q or "",
            "total": total,
            "attempt_type": attempt_type or "all",
            "attempt_operator": attempt_operator or "",
            "attempt_count": attempt_count_int,
            "print_log_operator": print_log_operator or "",
            "print_log_count": print_log_count_int,
            "print_log_mailed": print_log_mailed or "all",
            "scheduled_email_operator": scheduled_email_operator or "",
            "scheduled_email_count": scheduled_email_count_int,
            "failed_email_operator": failed_email_operator or "",
            "failed_email_count": failed_email_count_int,
            "status": status or "",
            "year": year or DEFAULT_YEAR,
            "available_years": get_available_years(db),
        },
    )


@router.get("/leads/{lead_id}/entity-intel")
async def lead_entity_intelligence(
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)

    prop = get_property_details_for_lead(db, lead)

    if not prop:
        raise HTTPException(
            status_code=404,
            detail="Linked property record not found for this lead.",
        )

    payload = build_gpt_payload(lead, prop)

    try:
        analysis = await run_in_threadpool(fetch_entity_intelligence, payload)
    except GPTConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GPTServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"input": payload, "analysis": analysis}




@router.get("/leads/{lead_id}/view", response_class=HTMLResponse)
def view_lead(
    request: Request,
    lead_id: int,
    q: str | None = Query(None),
    attempt_type: str | None = Query(None),
    attempt_operator: str | None = Query(None),
    attempt_count: str | None = Query(None),
    print_log_operator: str | None = Query(None),
    print_log_count: str | None = Query(None),
    print_log_mailed: str | None = Query(None),
    scheduled_email_operator: str | None = Query(None),
    scheduled_email_count: str | None = Query(None),
    failed_email_operator: str | None = Query(None),
    failed_email_count: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Read-only view of a lead."""
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    def parse_count(value: str | None) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    
    attempt_count_int = parse_count(attempt_count)
    print_log_count_int = parse_count(print_log_count)
    scheduled_email_count_int = parse_count(scheduled_email_count)
    failed_email_count_int = parse_count(failed_email_count)
    
    nav = lead_navigation_info(
        db, lead_id, q, attempt_type, attempt_operator, attempt_count_int,
        print_log_operator, print_log_count_int, print_log_mailed,
        scheduled_email_operator, scheduled_email_count_int,
        failed_email_operator, failed_email_count_int, status
    )

    # Sort contacts to put primary first
    contacts = sorted(
        lead.contacts,
        key=lambda c: (not c.is_primary, c.id),
        reverse=False
    ) if lead.contacts else []
    attempts = sorted(
        lead.attempts,
        key=lambda attempt: attempt.created_at or datetime.min,
        reverse=True,
    )
    comments = sorted(
        lead.comments,
        key=lambda comment: comment.created_at or datetime.min,
        reverse=True,
    )

    # Get primary property and all properties
    primary_property = get_primary_property(lead)
    all_properties = sorted(
        lead.properties,
        key=lambda p: (not p.is_primary, p.added_at),
        reverse=False
    ) if lead.properties else []
    
    # Fetch property details for each property to get holder names
    from services.property_service import get_property_by_raw_hash
    properties_with_details = []
    for prop in all_properties:
        prop_details = None
        if prop.property_raw_hash:
            prop_details = get_property_by_raw_hash(db, prop.property_raw_hash)
        properties_with_details.append((prop, prop_details))
    
    property_details = get_property_details_for_lead(db, lead)
    phone_script_context = _build_phone_script_context(
        lead.owner_name,
        primary_property.property_id if primary_property else None,
        primary_property.property_amount if primary_property else None,
        property_details,
    )

    print_logs = get_print_logs_for_lead(db, lead.id)
    print_logs_json = json.dumps(
        [serialize_print_log(log) for log in print_logs],
        default=str,
    )

    return templates.TemplateResponse(
        "lead_form.html",
        {
            "request": request,
            "lead": lead,
            "mode": "view",
            "primary_property": primary_property,
            "all_properties": all_properties,
            "properties_with_details": properties_with_details,
            "property_id": primary_property.property_id if primary_property else "",
            "owner_name": lead.owner_name,
            "property_amount": primary_property.property_amount if primary_property else None,
            "statuses": list(LeadStatus),
            "contacts": contacts,
            "attempts": attempts,
            "channels": list(ContactChannel),
            "comments": comments,
            "contact_edit_target": None,
            "owner_types": list(OwnerType),
            "business_owner_statuses": list(BusinessOwnerStatus),
            "owner_sizes": list(OwnerSize),
            "individual_owner_statuses": list(IndividualOwnerStatus),
            "contact_types": list(ContactType),
            "owner_type": lead.owner_type,
            "business_owner_status": lead.business_owner_status,
            "owner_size": lead.owner_size,
            "new_business_name": lead.new_business_name or "",
            "individual_owner_status": lead.individual_owner_status,
            "property_raw_hash": primary_property.property_raw_hash if primary_property else "",
            "can_generate_letters": bool(primary_property and primary_property.property_raw_hash),
            "phone_scripts": PHONE_SCRIPTS,
            "phone_scripts_json": PHONE_SCRIPTS_JSON,
            "phone_script_context_json": json.dumps(phone_script_context, default=str),
            "print_logs_json": print_logs_json,
            "prev_lead_id": nav["prev_lead_id"],
            "next_lead_id": nav["next_lead_id"],
            "filter_params": {
                "q": q or "",
                "attempt_type": attempt_type or "",
                "attempt_operator": attempt_operator or "",
                "attempt_count": attempt_count or "",
                "print_log_operator": print_log_operator or "",
                "print_log_count": print_log_count or "",
                "print_log_mailed": print_log_mailed or "",
                "scheduled_email_operator": scheduled_email_operator or "",
                "scheduled_email_count": scheduled_email_count or "",
                "failed_email_operator": failed_email_operator or "",
                "failed_email_count": failed_email_count or "",
                "status": status or "",
            },
        },
    )


@router.get("/leads/{lead_id}/edit", response_class=HTMLResponse)
def edit_lead(
    request: Request,
    lead_id: int,
    edit_contact_id: int | None = None,
    q: str | None = Query(None),
    attempt_type: str | None = Query(None),
    attempt_operator: str | None = Query(None),
    attempt_count: str | None = Query(None),
    print_log_operator: str | None = Query(None),
    print_log_count: str | None = Query(None),
    print_log_mailed: str | None = Query(None),
    scheduled_email_operator: str | None = Query(None),
    scheduled_email_count: str | None = Query(None),
    failed_email_operator: str | None = Query(None),
    failed_email_count: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    if not is_lead_editable(lead):
        filter_query = build_filter_query_string(
            q, attempt_type, attempt_operator, attempt_count,
            print_log_operator, print_log_count, print_log_mailed,
            scheduled_email_operator, scheduled_email_count,
            failed_email_operator, failed_email_count, status
        )
        return RedirectResponse(url=f"/leads/{lead_id}/view{filter_query}", status_code=303)
    
    def parse_count(value: str | None) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    
    attempt_count_int = parse_count(attempt_count)
    print_log_count_int = parse_count(print_log_count)
    scheduled_email_count_int = parse_count(scheduled_email_count)
    failed_email_count_int = parse_count(failed_email_count)
    
    nav = lead_navigation_info(
        db, lead_id, q, attempt_type, attempt_operator, attempt_count_int,
        print_log_operator, print_log_count_int, print_log_mailed,
        scheduled_email_operator, scheduled_email_count_int,
        failed_email_operator, failed_email_count_int, status
    )

    # Sort contacts to put primary first
    contacts = sorted(
        lead.contacts,
        key=lambda c: (not c.is_primary, c.id),
        reverse=False
    ) if lead.contacts else []
    attempts = sorted(
        lead.attempts,
        key=lambda attempt: attempt.created_at or datetime.min,
        reverse=True,
    )
    comments = sorted(
        lead.comments,
        key=lambda comment: comment.created_at or datetime.min,
        reverse=True,
    )

    # Get primary property and all properties
    primary_property = get_primary_property(lead)
    all_properties = sorted(
        lead.properties,
        key=lambda p: (not p.is_primary, p.added_at),
        reverse=False
    ) if lead.properties else []
    
    # Fetch property details for each property to get holder names
    from services.property_service import get_property_by_raw_hash
    properties_with_details = []
    for prop in all_properties:
        prop_details = None
        if prop.property_raw_hash:
            prop_details = get_property_by_raw_hash(db, prop.property_raw_hash)
        properties_with_details.append((prop, prop_details))
    
    property_details = get_property_details_for_lead(db, lead)
    phone_script_context = _build_phone_script_context(
        lead.owner_name,
        primary_property.property_id if primary_property else None,
        primary_property.property_amount if primary_property else None,
        property_details,
    )

    contact_edit_target = None
    if edit_contact_id:
        contact_edit_target = next(
            (contact for contact in contacts if contact.id == edit_contact_id),
            None,
        )

    print_logs = get_print_logs_for_lead(db, lead.id)
    print_logs_json = json.dumps(
        [serialize_print_log(log) for log in print_logs],
        default=str,
    )
    
    journey_hidden_statuses = {
        LeadStatus.new,
        LeadStatus.researching,
        LeadStatus.invalid,
        LeadStatus.competitor_claimed
    }
    
    journey_data = None
    if lead.status not in journey_hidden_statuses:
        journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
        journey_data = get_journey_data(db, lead_id) if journey else None
    
    journey_json = json.dumps(journey_data, default=str) if journey_data else "null"

    return templates.TemplateResponse(
        "lead_form.html",
        {
            "request": request,
            "lead": lead,
            "mode": "edit",
            "primary_property": primary_property,
            "all_properties": all_properties,
            "properties_with_details": properties_with_details,
            "property_id": primary_property.property_id if primary_property else "",
            "owner_name": lead.owner_name,
            "property_amount": primary_property.property_amount if primary_property else None,
            "statuses": list(LeadStatus),
            "contacts": contacts,
            "attempts": attempts,
            "journey_data": journey_json,
            "channels": list(ContactChannel),
            "comments": comments,
            "contact_edit_target": contact_edit_target,
            "owner_types": list(OwnerType),
            "business_owner_statuses": list(BusinessOwnerStatus),
            "owner_sizes": list(OwnerSize),
            "individual_owner_statuses": list(IndividualOwnerStatus),
            "contact_types": list(ContactType),
            "owner_type": lead.owner_type,
            "business_owner_status": lead.business_owner_status,
            "owner_size": lead.owner_size,
            "new_business_name": lead.new_business_name or "",
            "individual_owner_status": lead.individual_owner_status,
            "property_raw_hash": primary_property.property_raw_hash if primary_property else "",
            "can_generate_letters": bool(primary_property and primary_property.property_raw_hash),
            "phone_scripts": PHONE_SCRIPTS,
            "phone_scripts_json": PHONE_SCRIPTS_JSON,
            "phone_script_context_json": json.dumps(phone_script_context, default=str),
            "print_logs_json": print_logs_json,
            "prev_lead_id": nav["prev_lead_id"],
            "next_lead_id": nav["next_lead_id"],
            "filter_params": {
                "q": q or "",
                "attempt_type": attempt_type or "",
                "attempt_operator": attempt_operator or "",
                "attempt_count": attempt_count or "",
                "print_log_operator": print_log_operator or "",
                "print_log_count": print_log_count or "",
                "print_log_mailed": print_log_mailed or "",
                "scheduled_email_operator": scheduled_email_operator or "",
                "scheduled_email_count": scheduled_email_count or "",
                "failed_email_operator": failed_email_operator or "",
                "failed_email_count": failed_email_count or "",
                "status": status or "",
            },
        },
    )


@router.post("/leads/{lead_id}/update")
def update_lead(
    lead_id: int,
    property_id: str = Form(...),
    owner_name: str = Form(...),
    property_amount: float | None = Form(None),
    property_raw_hash: str | None = Form(None),
    status: LeadStatus = Form(LeadStatus.new),
    notes: str | None = Form(None),
    owner_type: OwnerType = Form(OwnerType.business),
    business_owner_status: BusinessOwnerStatus | None = Form(None),
    owner_size: OwnerSize | None = Form(None),
    new_business_name: str | None = Form(None),
    individual_owner_status: IndividualOwnerStatus | None = Form(None),
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)

    normalized = normalize_owner_fields(
        owner_type, business_owner_status, owner_size, new_business_name,
        individual_owner_status, validate=True
    )

    old_status = lead.status
    lead.owner_name = owner_name
    lead.status = status
    lead.notes = notes
    lead.owner_type = owner_type
    lead.business_owner_status = normalized["business_owner_status"]
    lead.owner_size = normalized["owner_size"]
    lead.new_business_name = normalized["new_business_name"]
    lead.individual_owner_status = normalized["individual_owner_status"]
    lead.updated_at = datetime.now(timezone.utc)

    # Update primary property if it exists, otherwise create it
    primary_prop = get_primary_property(lead)
    if primary_prop and property_raw_hash:
        # Update existing primary property
        primary_prop.property_id = property_id
        primary_prop.property_amount = property_amount
        primary_prop.property_raw_hash = property_raw_hash
        mark_property_assigned(db, property_raw_hash, property_id)
    elif property_raw_hash:
        # Create new primary property if none exists
        primary_property = LeadProperty(
            lead_id=lead.id,
            property_id=property_id,
            property_raw_hash=property_raw_hash,
            property_amount=property_amount,
            is_primary=True,
        )
        db.add(primary_property)
        mark_property_assigned(db, property_raw_hash, property_id)
    
    if old_status in {LeadStatus.new, LeadStatus.researching} and lead.status not in {LeadStatus.new, LeadStatus.researching, LeadStatus.invalid, LeadStatus.competitor_claimed}:
        primary_contact = db.query(LeadContact).filter(
            LeadContact.lead_id == lead_id,
            LeadContact.is_primary == True
        ).first()
        if primary_contact:
            existing_journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
            if not existing_journey:
                initialize_lead_journey(db, lead_id, primary_contact_id=primary_contact.id)

    db.commit()
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)


@router.post("/leads/{lead_id}/delete")
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)
    
    # Get all property hashes and IDs before deleting
    property_data = [
        (prop.property_raw_hash, prop.property_id)
        for prop in lead.properties
    ]
    
    db.delete(lead)
    db.flush()
    
    # Unmark each property if unused
    for property_raw_hash, property_id in property_data:
        unmark_property_if_unused(db, property_raw_hash, property_id)
    
    db.commit()
    
    return RedirectResponse(url="/leads", status_code=303)


@router.post("/leads/{lead_id}/properties/add")
def add_property_to_lead(
    lead_id: int,
    property_id: str = Form(...),
    property_raw_hash: str = Form(...),
    property_amount: float | None = Form(None),
    db: Session = Depends(get_db),
):
    """Add a property to a lead."""
    lead = get_lead_or_404(db, lead_id)
    
    # Check if property already assigned to any lead
    existing = db.scalar(
        select(LeadProperty).where(LeadProperty.property_raw_hash == property_raw_hash)
    )
    if existing:
        existing_lead = db.get(BusinessLead, existing.lead_id)
        raise HTTPException(
            status_code=400,
            detail=f"Property already assigned to Lead #{existing_lead.id}"
        )
    
    # Create new LeadProperty
    new_property = LeadProperty(
        lead_id=lead.id,
        property_id=property_id,
        property_raw_hash=property_raw_hash,
        property_amount=property_amount,
        is_primary=False,  # New properties are not primary by default
    )
    db.add(new_property)
    mark_property_assigned(db, property_raw_hash, property_id)
    db.commit()
    
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)


@router.post("/leads/{lead_id}/properties/{property_id}/remove")
def remove_property_from_lead(
    lead_id: int,
    property_id: str,
    db: Session = Depends(get_db),
):
    """Remove a property from a lead."""
    lead = get_lead_or_404(db, lead_id)
    
    prop = db.scalar(
        select(LeadProperty).where(
            LeadProperty.lead_id == lead_id,
            LeadProperty.property_id == property_id
        )
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    
    # Prevent deleting the only property
    property_count = db.scalar(
        select(func.count(LeadProperty.id)).where(LeadProperty.lead_id == lead_id)
    )
    if property_count <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the only property from a lead."
        )
    
    # Prevent deleting the primary property
    if prop.is_primary:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the primary property. Set another property as primary first."
        )
    
    property_raw_hash = prop.property_raw_hash
    db.delete(prop)
    unmark_property_if_unused(db, property_raw_hash, property_id)
    db.commit()
    
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)


@router.post("/leads/{lead_id}/properties/{property_id}/set-primary")
def set_primary_property(
    lead_id: int,
    property_id: str,
    db: Session = Depends(get_db),
):
    """Set a property as primary for a lead."""
    lead = get_lead_or_404(db, lead_id)
    
    prop = db.scalar(
        select(LeadProperty).where(
            LeadProperty.lead_id == lead_id,
            LeadProperty.property_id == property_id
        )
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    
    # Set all properties for this lead to is_primary=False
    db.execute(
        update(LeadProperty)
        .where(LeadProperty.lead_id == lead_id)
        .values(is_primary=False)
    )
    
    # Set selected property to is_primary=True
    prop.is_primary = True
    db.commit()
    
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)


@router.get("/leads/{lead_id}/properties/related")
def get_related_properties_for_lead(
    lead_id: int,
    db: Session = Depends(get_db),
):
    """Get related properties for an existing lead (same owner_name, not already assigned)."""
    lead = get_lead_or_404(db, lead_id)
    
    from services.property_service import find_related_properties_by_owner_name
    
    related_props = find_related_properties_by_owner_name(
        db, 
        lead.owner_name, 
        exclude_lead_id=lead_id
    )
    
    # Format for JSON response
    result = []
    for prop in related_props:
        # Check if this property is already in the lead's properties
        already_in_lead = db.scalar(
            select(LeadProperty).where(
                LeadProperty.lead_id == lead_id,
                LeadProperty.property_raw_hash == prop.get("raw_hash")
            )
        ) is not None
        
        if not already_in_lead:
            # Convert Decimal to float for JSON serialization
            property_amount = prop.get("propertyamount")
            if property_amount is not None:
                if isinstance(property_amount, Decimal):
                    property_amount = float(property_amount)
                elif property_amount is not None:
                    try:
                        property_amount = float(property_amount)
                    except (TypeError, ValueError):
                        property_amount = None
            else:
                property_amount = None
            
            result.append({
                "property_id": str(prop.get("propertyid") or ""),
                "property_raw_hash": str(prop.get("raw_hash") or ""),
                "property_amount": property_amount,
                "holder_name": str(prop.get("holdername") or ""),
                "owner_name": str(prop.get("ownername") or ""),
            })
    
    return JSONResponse(content={"properties": result})


@router.get("/properties/related")
def get_related_properties_by_owner_name(
    owner_name: str = Query(..., description="Owner name to search for"),
    exclude_lead_id: int | None = Query(None, description="Lead ID to exclude from assignment check"),
    db: Session = Depends(get_db),
):
    """Get related properties by owner name (for new lead creation)."""
    from services.property_service import find_related_properties_by_owner_name
    
    related_props = find_related_properties_by_owner_name(
        db, 
        owner_name, 
        exclude_lead_id=exclude_lead_id
    )
    
    # Format for JSON response
    result = []
    for prop in related_props:
        # Check if property is already assigned to any lead
        already_assigned = db.scalar(
            select(LeadProperty).where(
                LeadProperty.property_raw_hash == prop.get("raw_hash")
            )
        ) is not None
        
        if not already_assigned:
            # Convert Decimal to float for JSON serialization
            property_amount = prop.get("propertyamount")
            if property_amount is not None:
                if isinstance(property_amount, Decimal):
                    property_amount = float(property_amount)
                elif property_amount is not None:
                    try:
                        property_amount = float(property_amount)
                    except (TypeError, ValueError):
                        property_amount = None
            else:
                property_amount = None
            
            result.append({
                "property_id": str(prop.get("propertyid") or ""),
                "property_raw_hash": str(prop.get("raw_hash") or ""),
                "property_amount": property_amount,
                "holder_name": str(prop.get("holdername") or ""),
                "owner_name": str(prop.get("ownername") or ""),
            })
    
    return JSONResponse(content={"properties": result})


@router.post("/leads/{lead_id}/properties/add-bulk")
def add_properties_bulk(
    lead_id: int,
    property_ids: str = Form(...),  # JSON array of property data
    db: Session = Depends(get_db),
):
    """Add multiple properties to a lead at once."""
    lead = get_lead_or_404(db, lead_id)
    
    try:
        properties_data = json.loads(property_ids)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid property_ids JSON")
    
    if not isinstance(properties_data, list):
        raise HTTPException(status_code=400, detail="property_ids must be an array")
    
    added_count = 0
    errors = []
    
    for prop_data in properties_data:
        property_id = prop_data.get("property_id")
        property_raw_hash = prop_data.get("property_raw_hash")
        property_amount = prop_data.get("property_amount")
        
        if not property_id or not property_raw_hash:
            errors.append(f"Missing property_id or property_raw_hash for one property")
            continue
        
        # Check if property already assigned to any lead
        existing = db.scalar(
            select(LeadProperty).where(LeadProperty.property_raw_hash == property_raw_hash)
        )
        if existing:
            if existing.lead_id == lead_id:
                # Already in this lead, skip
                continue
            else:
                existing_lead = db.get(BusinessLead, existing.lead_id)
                errors.append(f"Property {property_id} already assigned to Lead #{existing_lead.id}")
                continue
        
        # Create new LeadProperty
        new_property = LeadProperty(
            lead_id=lead.id,
            property_id=property_id,
            property_raw_hash=property_raw_hash,
            property_amount=property_amount,
            is_primary=False,
        )
        db.add(new_property)
        mark_property_assigned(db, property_raw_hash, property_id)
        added_count += 1
    
    db.commit()
    
    if errors:
        # Still return success but include errors
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "added_count": added_count,
                "errors": errors,
                "message": f"Added {added_count} properties. {len(errors)} errors occurred."
            }
        )
    
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)


@router.post("/leads/bulk/change-status")
async def bulk_change_status(
    request: Request,
    db: Session = Depends(get_db),
):
    """Bulk change status for multiple leads."""
    body = await request.json()
    lead_ids = body.get("lead_ids", [])
    status = body.get("status")
    
    if not lead_ids:
        raise HTTPException(status_code=400, detail="No leads selected")
    
    if not status:
        raise HTTPException(status_code=400, detail="Status is required")
    
    try:
        status_enum = LeadStatus[status]
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    updated = 0
    skipped = 0
    
    for lead_id in lead_ids:
        lead = db.get(BusinessLead, lead_id)
        if not lead:
            skipped += 1
            continue
        
        if not is_lead_editable(lead):
            skipped += 1
            continue
        
        lead.status = status_enum
        lead.updated_at = datetime.now(timezone.utc)
        updated += 1
    
    db.commit()
    
    return JSONResponse(content={
        "updated": updated,
        "skipped": skipped,
        "total": len(lead_ids)
    })


@router.post("/leads/bulk/mark-mail-sent")
async def bulk_mark_mail_sent(
    request: Request,
    db: Session = Depends(get_db),
):
    """Bulk mark all unmailed print logs as mailed for multiple leads."""
    from models import PrintLog, LeadAttempt
    from services.journey_service import link_attempt_to_milestone
    
    body = await request.json()
    lead_ids = body.get("lead_ids", [])
    
    if not lead_ids:
        raise HTTPException(status_code=400, detail="No leads selected")
    
    leads_processed = 0
    print_logs_marked = 0
    attempts_created = 0
    skipped = 0
    
    for lead_id in lead_ids:
        lead = db.get(BusinessLead, lead_id)
        if not lead:
            skipped += 1
            continue
        
        unmailed_logs = db.query(PrintLog).filter(
            PrintLog.lead_id == lead_id,
            PrintLog.mailed == False
        ).all()
        
        if not unmailed_logs:
            skipped += 1
            continue
        
        leads_processed += 1
        
        for log in unmailed_logs:
            if log.mailed:
                continue
            
            next_attempt_number = get_next_attempt_number(db, lead_id)
            
            attempt = LeadAttempt(
                lead_id=lead_id,
                contact_id=log.contact_id,
                channel=ContactChannel.mail,
                attempt_number=next_attempt_number,
                outcome="Letter mailed",
                notes=f"Letter mailed ({log.filename})",
            )
            db.add(attempt)
            db.flush()
            
            link_attempt_to_milestone(db, attempt)
            
            log.mailed = True
            log.mailed_at = datetime.now(timezone.utc)
            log.attempt_id = attempt.id
            
            print_logs_marked += 1
            attempts_created += 1
    
    db.commit()
    
    return JSONResponse(content={
        "leads_processed": leads_processed,
        "print_logs_marked": print_logs_marked,
        "attempts_created": attempts_created,
        "skipped": skipped,
        "total": len(lead_ids)
    })

