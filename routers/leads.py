"""
Core lead routes - handles lead CRUD operations, listing, and bulk actions.
"""

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, cast, String, and_, exists

from db import get_db
from models import (
    BusinessLead,
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
        existing_lead = db.scalar(
            select(BusinessLead).where(
                or_(
                    BusinessLead.property_raw_hash == prop["raw_hash"],
                    BusinessLead.property_id == prop["propertyid"],
                )
            )
        )
        if existing_lead:
            return RedirectResponse(
                url=f"/leads/{existing_lead.id}/edit",
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

    return templates.TemplateResponse(
        "lead_form.html",
        {
            "request": request,
            "lead": None,
            "mode": "create",
            "property_id": prop["propertyid"],
            "owner_name": prop["ownername"],
            "property_amount": prop["propertyamount"],
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

    lead = BusinessLead(
        property_id=property_id,
        owner_name=owner_name,
        property_amount=property_amount,
        status=status,
        notes=notes,
        owner_type=owner_type,
        business_owner_status=normalized["business_owner_status"],
        owner_size=normalized["owner_size"],
        new_business_name=normalized["new_business_name"],
        individual_owner_status=normalized["individual_owner_status"],
        property_raw_hash=property_raw_hash,
    )
    db.add(lead)
    mark_property_assigned(db, property_raw_hash, property_id)
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
    year_filter = or_(
        and_(
            BusinessLead.property_raw_hash.is_not(None),
            exists(
                select(1)
                .select_from(prop_table)
                .where(prop_table.c.row_hash == BusinessLead.property_raw_hash)
                .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
            )
        ),
        and_(
            BusinessLead.property_id.is_not(None),
            exists(
                select(1)
                .select_from(prop_table)
                .where(cast(prop_table.c.propertyid, String) == BusinessLead.property_id)
                .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
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

    leads_with_flags = [(lead, is_lead_editable(lead)) for lead in leads]

    return templates.TemplateResponse(
        "leads.html",
        {
            "request": request,
            "leads_with_flags": leads_with_flags,
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

    contacts = list(lead.contacts)
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

    property_details = get_property_details_for_lead(db, lead)
    phone_script_context = _build_phone_script_context(
        lead.owner_name,
        lead.property_id,
        lead.property_amount,
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
            "property_id": lead.property_id,
            "owner_name": lead.owner_name,
            "property_amount": lead.property_amount,
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
            "property_raw_hash": lead.property_raw_hash,
            "can_generate_letters": False,
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

    contacts = list(lead.contacts)
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

    property_details = get_property_details_for_lead(db, lead)
    phone_script_context = _build_phone_script_context(
        lead.owner_name,
        lead.property_id,
        lead.property_amount,
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
            "property_id": lead.property_id,
            "owner_name": lead.owner_name,
            "property_amount": lead.property_amount,
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
            "property_raw_hash": lead.property_raw_hash,
            "can_generate_letters": bool(lead.property_raw_hash or lead.property_id),
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
    lead.property_id = property_id
    lead.owner_name = owner_name
    lead.property_amount = property_amount
    lead.status = status
    lead.notes = notes
    lead.owner_type = owner_type
    lead.business_owner_status = normalized["business_owner_status"]
    lead.owner_size = normalized["owner_size"]
    lead.new_business_name = normalized["new_business_name"]
    lead.individual_owner_status = normalized["individual_owner_status"]
    lead.property_raw_hash = property_raw_hash

    lead.updated_at = datetime.now(timezone.utc)

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
    
    property_raw_hash = lead.property_raw_hash
    property_id = lead.property_id
    
    db.delete(lead)
    db.flush()
    unmark_property_if_unused(db, property_raw_hash, property_id)
    db.commit()
    
    return RedirectResponse(url="/leads", status_code=303)


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

