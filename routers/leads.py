"""
Lead core routes - CRUD, listing, and lead detail views.
"""

from datetime import datetime, timezone
import logging
import json
from decimal import Decimal
from io import BytesIO

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import Integer, String, and_, cast, exists, func, or_, select
from sqlalchemy.orm import Session

from db import get_db
from helpers.filter_helpers import build_filter_query_string, build_lead_filters, lead_navigation_info
from helpers.lead_ui import build_phone_script_context, parse_count
from helpers.phone_scripts import get_phone_scripts_json, load_phone_scripts
from helpers.print_log_helpers import get_print_logs_for_lead, serialize_print_log
from helpers.property_helpers import get_primary_property
from models import (
    BusinessOwnerStatus,
    ContactChannel,
    ContactType,
    IndividualOwnerStatus,
    Lead,
    LeadContact,
    LeadJourney,
    LeadProperty,
    LeadStatus,
    OwnerSize,
    OwnerType,
)
from services.agreement_service import get_latest_claim_summary
from services.journey_service import get_journey_data, initialize_lead_journey
from services.letter_service import get_property_for_lead, render_one_pager_pdf
from services.property_service import (
    DEFAULT_YEAR,
    PROPERTY_MIN_AMOUNT,
    format_property_address,
    get_available_years,
    get_property_by_id,
    get_property_details_for_lead,
    get_property_table_for_year,
    mark_property_assigned,
    unmark_property_if_unused,
)
from utils import get_lead_or_404, is_lead_editable, normalize_owner_fields

logger = logging.getLogger(__name__)

# Import shared templates from main to ensure filters are registered
# This will be set by main.py after filters are registered
templates = None  # Will be set by main.py
PAGE_SIZE = 20

PHONE_SCRIPTS = load_phone_scripts()
PHONE_SCRIPTS_JSON = get_phone_scripts_json()

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
        existing_property = db.scalar(
            select(LeadProperty).where(LeadProperty.property_raw_hash == prop["raw_hash"])
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

    phone_script_context = build_phone_script_context(
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
        exclude_lead_id=None,
    )

    # Format related properties for template
    related_properties_list = []
    for rp in related_props:
        if rp.get("raw_hash") != prop.get("raw_hash"):
            already_assigned = (
                db.scalar(
                    select(LeadProperty).where(
                        LeadProperty.property_raw_hash == rp.get("raw_hash")
                    )
                )
                is not None
            )
            if not already_assigned:
                property_amount = rp.get("propertyamount")
                if property_amount is not None:
                    if isinstance(property_amount, Decimal):
                        property_amount = float(property_amount)
                    else:
                        try:
                            property_amount = float(property_amount)
                        except (TypeError, ValueError):
                            property_amount = None
                else:
                    property_amount = None

                related_properties_list.append(
                    {
                        "property_id": rp.get("propertyid") or "",
                        "property_raw_hash": rp.get("raw_hash") or "",
                        "property_amount": property_amount,
                        "holder_name": rp.get("holdername") or "",
                        "owner_name": rp.get("ownername") or "",
                        "reportyear": str(rp.get("reportyear") or "")
                        if rp.get("reportyear")
                        else None,
                    }
                )

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
    additional_properties: str | None = Form(None),
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
        owner_type,
        business_owner_status,
        owner_size,
        new_business_name,
        individual_owner_status,
        validate=True,
    )

    lead = Lead(
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
    db.flush()

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

    if additional_properties:
        try:
            additional_props_data = json.loads(additional_properties)
            if isinstance(additional_props_data, list):
                for prop_data in additional_props_data:
                    add_prop_id = prop_data.get("property_id")
                    add_prop_hash = prop_data.get("property_raw_hash")
                    add_prop_amount = prop_data.get("property_amount")

                    if add_prop_id and add_prop_hash:
                        existing = db.scalar(
                            select(LeadProperty).where(
                                LeadProperty.property_raw_hash == add_prop_hash
                            )
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
    attempt_type = attempt_type.strip() if attempt_type and attempt_type.strip() else None
    attempt_operator = attempt_operator.strip() if attempt_operator and attempt_operator.strip() else None
    print_log_operator = print_log_operator.strip() if print_log_operator and print_log_operator.strip() else None
    print_log_mailed = print_log_mailed.strip() if print_log_mailed and print_log_mailed.strip() else None
    scheduled_email_operator = (
        scheduled_email_operator.strip()
        if scheduled_email_operator and scheduled_email_operator.strip()
        else None
    )
    failed_email_operator = (
        failed_email_operator.strip() if failed_email_operator and failed_email_operator.strip() else None
    )
    status = status.strip() if status and status.strip() else None

    attempt_count_int = parse_count(attempt_count)
    print_log_count_int = parse_count(print_log_count)
    scheduled_email_count_int = parse_count(scheduled_email_count)
    failed_email_count_int = parse_count(failed_email_count)

    if page < 1:
        page = 1

    if not year:
        year = DEFAULT_YEAR

    available_years = get_available_years(db)
    if year not in available_years:
        year = DEFAULT_YEAR

    stmt = select(Lead)
    count_stmt = select(func.count()).select_from(Lead)

    prop_table = get_property_table_for_year(year)
    year_filter = exists(
        select(1)
        .select_from(LeadProperty)
        .where(LeadProperty.lead_id == Lead.id)
        .where(
            or_(
                exists(
                    select(1)
                    .select_from(prop_table)
                    .where(prop_table.c.row_hash == LeadProperty.property_raw_hash)
                    .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
                    .where(cast(prop_table.c.reportyear, Integer) == int(year))
                ),
                exists(
                    select(1)
                    .select_from(prop_table)
                    .where(cast(prop_table.c.propertyid, String) == LeadProperty.property_id)
                    .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
                    .where(cast(prop_table.c.reportyear, Integer) == int(year))
                ),
            )
        )
    )

    filters = build_lead_filters(
        q,
        attempt_type,
        attempt_operator,
        attempt_count_int,
        print_log_operator,
        print_log_count_int,
        print_log_mailed,
        scheduled_email_operator,
        scheduled_email_count_int,
        failed_email_operator,
        failed_email_count_int,
        status,
    )

    filters.append(year_filter)

    if filters:
        combined_filter = and_(*filters)
        stmt = stmt.where(combined_filter)
        count_stmt = count_stmt.where(combined_filter)

    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(Lead.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)

    leads = db.scalars(stmt).all()

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1

    leads_with_data = []
    for lead in leads:
        primary_prop = get_primary_property(lead)
        has_claim = get_latest_claim_summary(db, lead.id) is not None
        leads_with_data.append((lead, is_lead_editable(lead), primary_prop, has_claim))

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
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    attempt_count_int = parse_count(attempt_count)
    print_log_count_int = parse_count(print_log_count)
    scheduled_email_count_int = parse_count(scheduled_email_count)
    failed_email_count_int = parse_count(failed_email_count)

    nav = lead_navigation_info(
        db,
        lead_id,
        q,
        attempt_type,
        attempt_operator,
        attempt_count_int,
        print_log_operator,
        print_log_count_int,
        print_log_mailed,
        scheduled_email_operator,
        scheduled_email_count_int,
        failed_email_operator,
        failed_email_count_int,
        status,
    )

    contacts = (
        sorted(
            lead.contacts,
            key=lambda c: (not c.is_primary, c.id),
            reverse=False,
        )
        if lead.contacts
        else []
    )
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

    primary_property = get_primary_property(lead)
    all_properties = (
        sorted(
            lead.properties,
            key=lambda p: (not p.is_primary, p.added_at),
            reverse=False,
        )
        if lead.properties
        else []
    )

    from services.property_service import get_property_by_raw_hash

    properties_with_details = []
    for prop in all_properties:
        prop_details = None
        if prop.property_raw_hash:
            prop_details = get_property_by_raw_hash(db, prop.property_raw_hash)
            if prop_details:
                prop_details["formatted_address"] = format_property_address(prop_details)
        properties_with_details.append((prop, prop_details))

    property_details = get_property_details_for_lead(db, lead)
    phone_script_context = build_phone_script_context(
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
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not is_lead_editable(lead):
        filter_query = build_filter_query_string(
            q,
            attempt_type,
            attempt_operator,
            attempt_count,
            print_log_operator,
            print_log_count,
            print_log_mailed,
            scheduled_email_operator,
            scheduled_email_count,
            failed_email_operator,
            failed_email_count,
            status,
        )
        return RedirectResponse(url=f"/leads/{lead_id}/view{filter_query}", status_code=303)

    attempt_count_int = parse_count(attempt_count)
    print_log_count_int = parse_count(print_log_count)
    scheduled_email_count_int = parse_count(scheduled_email_count)
    failed_email_count_int = parse_count(failed_email_count)

    nav = lead_navigation_info(
        db,
        lead_id,
        q,
        attempt_type,
        attempt_operator,
        attempt_count_int,
        print_log_operator,
        print_log_count_int,
        print_log_mailed,
        scheduled_email_operator,
        scheduled_email_count_int,
        failed_email_operator,
        failed_email_count_int,
        status,
    )

    contacts = (
        sorted(
            lead.contacts,
            key=lambda c: (not c.is_primary, c.id),
            reverse=False,
        )
        if lead.contacts
        else []
    )
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

    primary_property = get_primary_property(lead)
    all_properties = (
        sorted(
            lead.properties,
            key=lambda p: (not p.is_primary, p.added_at),
            reverse=False,
        )
        if lead.properties
        else []
    )

    from services.property_service import get_property_by_raw_hash

    properties_with_details = []
    for prop in all_properties:
        prop_details = None
        if prop.property_raw_hash:
            prop_details = get_property_by_raw_hash(db, prop.property_raw_hash)
            if prop_details:
                prop_details["formatted_address"] = format_property_address(prop_details)
        properties_with_details.append((prop, prop_details))

    property_details = get_property_details_for_lead(db, lead)
    phone_script_context = build_phone_script_context(
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
        LeadStatus.competitor_claimed,
    }

    journey_data = None
    if lead.status not in journey_hidden_statuses:
        journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
        journey_data = get_journey_data(db, lead_id) if journey else None

    journey_json = json.dumps(journey_data, default=str) if journey_data else "null"

    latest_claim = get_latest_claim_summary(db, lead.id)

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
            "latest_claim": latest_claim,
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
        owner_type,
        business_owner_status,
        owner_size,
        new_business_name,
        individual_owner_status,
        validate=True,
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

    primary_prop = get_primary_property(lead)
    if primary_prop and property_raw_hash:
        primary_prop.property_id = property_id
        primary_prop.property_amount = property_amount
        primary_prop.property_raw_hash = property_raw_hash
        mark_property_assigned(db, property_raw_hash, property_id)
    elif property_raw_hash:
        primary_property = LeadProperty(
            lead_id=lead.id,
            property_id=property_id,
            property_raw_hash=property_raw_hash,
            property_amount=property_amount,
            is_primary=True,
        )
        db.add(primary_property)
        mark_property_assigned(db, property_raw_hash, property_id)

    if old_status in {LeadStatus.new, LeadStatus.researching} and lead.status not in {
        LeadStatus.new,
        LeadStatus.researching,
        LeadStatus.competitor_claimed,
    }:
        primary_contact = (
            db.query(LeadContact)
            .filter(LeadContact.lead_id == lead_id, LeadContact.is_primary == True)
            .first()
        )
        if primary_contact:
            existing_journey = (
                db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
            )
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

    property_data = [
        (prop.property_raw_hash, prop.property_id) for prop in lead.properties
    ]

    db.delete(lead)
    db.flush()

    for property_raw_hash, property_id in property_data:
        unmark_property_if_unused(db, property_raw_hash, property_id)

    db.commit()

    return RedirectResponse(url="/leads", status_code=303)


@router.get("/leads/{lead_id}/one-pager")
def generate_one_pager(
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)

    property_details = get_property_for_lead(db, lead)
    if not property_details:
        raise HTTPException(
            status_code=400,
            detail="Lead is not associated with a property record.",
        )

    pdf_bytes, filename = render_one_pager_pdf(templates.env, lead, property_details, db)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)


@router.get("/leads/{lead_id}/claim")
def lead_claim(
    lead_id: int,
    db: Session = Depends(get_db),
):
    try:
        claim = get_latest_claim_summary(db, lead_id)
    except Exception:
        logger.exception("lead_claim lookup failed")
        raise HTTPException(status_code=500, detail="Failed to fetch claim")
    if not claim:
        raise HTTPException(status_code=404, detail="No claim found")
    return claim
