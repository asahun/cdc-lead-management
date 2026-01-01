"""
Core lead routes - handles lead CRUD operations, listing, and bulk actions.
"""

from datetime import datetime, timezone
import re
from io import BytesIO
import shutil
import json
import logging
from pathlib import Path
import uuid
import mimetypes

from fastapi import APIRouter, Depends, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, FileResponse
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, cast, String, Integer, and_, exists, update, text

from db import get_db
from models import (
    Lead,
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
    Claim,
    ClaimDocument,
    ClaimEvent,
)
from typing import Any, List
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
from services.letter_service import render_one_pager_pdf, get_property_for_lead
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
from services.gpt_service import (
    fetch_entity_intelligence,
)
from services.agreement_service import (
    create_claim_from_lead,
    get_latest_claim_summary,
    generate_agreements_for_claim,
    generate_agreements,
    list_events,
    list_documents,
    list_events_for_claim,
    list_documents_for_claim,
)
from services.sos_service import SOSService
from services.entity_intelligence_orchestrator import EntityIntelligenceOrchestrator
from services.exceptions import GPTConfigError, GPTServiceError, SOSDataError
from fastapi.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

CLAIM_STATUS_VALUES = [
    "claim_created",
    "agreement_generated",
    "agreement_sent",
    "agreement_signed",
    "claim_preparing",
    "claim_submitted",
    "pending",
    "approved",
    "rejected",
    "more_info",
]


def _list_files_in_dir(dir_path: Path) -> List[dict]:
    files = []
    if not dir_path.exists() or not dir_path.is_dir():
        return files
    
    # Allowed file extensions: images and PDFs
    allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.svg'}
    
    for p in sorted(dir_path.iterdir()):
        if p.is_file():
            # Only include image and PDF files
            if p.suffix.lower() in allowed_extensions:
                files.append(
                    {
                        "name": p.name,
                        "path": str(p),
                        "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                    }
                )
    return files

# Import shared templates from main to ensure filters are registered
# This will be set by main.py after filters are registered
templates = None  # Will be set by main.py
PAGE_SIZE = 20

PHONE_SCRIPTS = load_phone_scripts()
PHONE_SCRIPTS_JSON = get_phone_scripts_json()


def _suffix_or_special_present(name: str) -> bool:
    """Detect if the original name contains legal suffix tokens or special characters."""
    if not name:
        return False
    lowered = name.lower()
    has_special = bool(re.search(r"[^\w\s]", lowered))
    suffix_pattern = r"\b(inc|inc\.|incorporated|corp|corporation|llc|l\.l\.c\.|ltd|limited|co|company|lp|l\.p\.|llp|l\.l\.p\.)\b"
    has_suffix = bool(re.search(suffix_pattern, lowered))
    return has_special or has_suffix


def _flip_allowed(base_normalized: str, original_name: str) -> bool:
    tokens = base_normalized.split()
    return len(tokens) == 3 and not _suffix_or_special_present(original_name)

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
                    "reportyear": str(rp.get("reportyear") or "") if rp.get("reportyear") else None,
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

    # Default to current year if not specified
    if not year:
        year = DEFAULT_YEAR
    
    # Validate year exists
    available_years = get_available_years(db)
    if year not in available_years:
        year = DEFAULT_YEAR

    stmt = select(Lead)
    count_stmt = select(func.count()).select_from(Lead)

    prop_table = get_property_table_for_year(year)
    # Filter leads that have properties matching the year's property table
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
    stmt = stmt.order_by(Lead.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)

    leads = db.scalars(stmt).all()

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1

    # Get primary property for each lead
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


@router.get("/leads/{lead_id}/entity-intel")
async def lead_entity_intelligence(
    lead_id: int,
    db: Session = Depends(get_db),
):
    logger.info(f"lead_entity_intelligence: Request for lead_id={lead_id}")
    lead = get_lead_or_404(db, lead_id)

    prop = get_property_details_for_lead(db, lead)
    logger.debug(f"lead_entity_intelligence: Property found: {prop is not None}")

    if not prop:
        raise HTTPException(
            status_code=404,
            detail="Linked property record not found for this lead.",
        )

    payload = build_gpt_payload(lead, prop)
    logger.debug(f"lead_entity_intelligence: GPT payload built: business_name='{payload.get('business_name')}', property_state='{payload.get('property_state')}'")

    try:
        analysis = await run_in_threadpool(fetch_entity_intelligence, payload, db)
        logger.info(f"lead_entity_intelligence: Analysis complete, response keys: {list(analysis.keys()) if analysis else 'None'}")
        
        # Debug: Check for new fields
        new_fields = ["status_profile", "address_profile", "contact_recommendation", "data_gaps", "ga_entity_mapping", "entitlement"]
        for field in new_fields:
            if field in analysis:
                field_value = analysis[field]
                if isinstance(field_value, dict):
                    logger.debug(f"lead_entity_intelligence: {field} present with keys: {list(field_value.keys())}")
                elif isinstance(field_value, list):
                    logger.debug(f"lead_entity_intelligence: {field} present as list with {len(field_value)} items")
                else:
                    logger.debug(f"lead_entity_intelligence: {field} = {field_value}")
            else:
                logger.warning(f"lead_entity_intelligence: {field} is MISSING from analysis response")
        
        logger.debug(f"lead_entity_intelligence: Analysis preview - chain_status={analysis.get('chain_assessment', {}).get('chain_status', 'N/A')}, current_entity={analysis.get('current_entity', {}).get('legal_name', 'N/A')}")
    except GPTConfigError as exc:
        logger.error(f"lead_entity_intelligence: GPTConfigError: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GPTServiceError as exc:
        logger.error(f"lead_entity_intelligence: GPTServiceError: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    response = {"input": payload, "analysis": analysis}
    logger.debug(f"lead_entity_intelligence: Returning response with input keys: {list(response.get('input', {}).keys())}, analysis keys: {list(response.get('analysis', {}).keys())}")
    return response


@router.get("/leads/{lead_id}/entity-intel/sos-options")
async def lead_entity_intel_sos_options(
    lead_id: int,
    flip: bool = Query(False, description="Apply flipped search (move first token to end)"),
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)
    prop = get_property_details_for_lead(db, lead)
    if not prop:
        raise HTTPException(status_code=404, detail="Linked property record not found for this lead.")

    owner_name = lead.owner_name or prop.get("ownername") or ""
    sos_service = SOSService(db)
    base_normalized = sos_service.normalize_business_name_without_suffixes(owner_name)
    if not base_normalized:
        return {
            "search_name_used": "",
            "flip_applied": False,
            "flip_allowed": False,
            "sos_records": [],
        }

    flip_allowed = _flip_allowed(base_normalized, owner_name)
    if flip and not flip_allowed:
        raise HTTPException(status_code=400, detail="Flip search not allowed for this name (requires exactly 3 tokens and no suffix/special chars).")

    search_name_used = sos_service.reorder_first_token_to_end(base_normalized) if flip else base_normalized
    try:
        sos_records = sos_service.search_by_normalized_name(search_name_used)
    except SOSDataError as exc:
        logger.error(f"lead_entity_intel_sos_options: SOS query failed: {exc}")
        raise HTTPException(status_code=502, detail="Failed to query SOS records") from exc

    return {
        "search_name_used": search_name_used,
        "flip_applied": flip,
        "flip_allowed": flip_allowed,
        "sos_records": sos_records,
    }


@router.post("/leads/{lead_id}/entity-intel/run")
async def lead_entity_intelligence_run(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)
    prop = get_property_details_for_lead(db, lead)
    if not prop:
        raise HTTPException(status_code=404, detail="Linked property record not found for this lead.")

    try:
        body = await request.json()
    except Exception:
        body = {}

    selected_sos_record = body.get("selected_sos_record") or None
    sos_search_name_used = body.get("sos_search_name_used") or None
    flip_applied = bool(body.get("flip_applied", False))

    payload = build_gpt_payload(lead, prop)
    payload.update(
        {
            "selected_sos_record": selected_sos_record,
            "sos_search_name_used": sos_search_name_used,
            "skip_sos_lookup": True,
        }
    )

    try:
        analysis = await run_in_threadpool(fetch_entity_intelligence, payload, db)
    except GPTConfigError as exc:
        logger.error(f"lead_entity_intelligence_run: GPTConfigError: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GPTServiceError as exc:
        logger.error(f"lead_entity_intelligence_run: GPTServiceError: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Redact SOS record if needed
    gpt_redacted_sos_data = None
    if selected_sos_record:
        sos_service = SOSService(db)
        gpt_redacted_sos_data = sos_service.redact_record(selected_sos_record)
    
    response = {
        "input": payload,
        "analysis": analysis,
        "selected_sos_data": selected_sos_record,
        "gpt_redacted_sos_data": gpt_redacted_sos_data,
        "meta": {
            "sos_search_name_used": sos_search_name_used,
            "flip_applied": flip_applied,
        },
    }
    return response




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
    lead = db.get(Lead, lead_id)
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
    lead = db.get(Lead, lead_id)
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
        LeadStatus.competitor_claimed
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
    
    if old_status in {LeadStatus.new, LeadStatus.researching} and lead.status not in {LeadStatus.new, LeadStatus.researching, LeadStatus.competitor_claimed}:
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
        existing_lead = db.get(Lead, existing.lead_id)
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
                "reportyear": str(prop.get("reportyear") or "") if prop.get("reportyear") else None,
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
                "reportyear": str(prop.get("reportyear") or "") if prop.get("reportyear") else None,
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
                existing_lead = db.get(Lead, existing.lead_id)
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
        lead = db.get(Lead, lead_id)
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
        lead = db.get(Lead, lead_id)
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


@router.get("/leads/{lead_id}/one-pager")
def generate_one_pager(
    lead_id: int,
    db: Session = Depends(get_db),
):
    """Generate a one-pager PDF for the lead (no contact context)."""
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


@router.post("/leads/{lead_id}/agreements/generate")
async def lead_generate_agreements(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.json()
    control_no = body.get("control_no") or ""
    formation_state = body.get("formation_state") or ""
    fee_pct = body.get("fee_pct") or "10"
    addendum_yes = bool(body.get("addendum_yes", False))

    try:
        result = generate_agreements(
            db=db,
            lead_id=lead_id,
            control_no=control_no,
            formation_state=formation_state,
            fee_pct=fee_pct,
            addendum_yes=addendum_yes,
            user=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception:
        logger.exception("lead_generate_agreements failed")
        raise HTTPException(status_code=500, detail="Failed to generate agreements")

    return result


@router.get("/leads/{lead_id}/agreements/events")
def lead_agreement_events(
    lead_id: int,
    db: Session = Depends(get_db),
):
    try:
        events = list_events(db, lead_id)
    except Exception:
        logger.exception("lead_agreement_events failed")
        raise HTTPException(status_code=500, detail="Failed to fetch agreement events")
    return {"events": events}


@router.get("/leads/{lead_id}/agreements/documents")
def lead_agreement_documents(
    lead_id: int,
    db: Session = Depends(get_db),
):
    try:
        docs = list_documents(db, lead_id)
    except Exception:
        logger.exception("lead_agreement_documents failed")
        raise HTTPException(status_code=500, detail="Failed to fetch agreement documents")
    return {"documents": docs}


@router.get("/leads/{lead_id}/claims/latest")
def lead_latest_claim(
    lead_id: int,
    db: Session = Depends(get_db),
):
    try:
        claim = get_latest_claim_summary(db, lead_id)
    except Exception:
        logger.exception("lead_latest_claim failed")
        raise HTTPException(status_code=500, detail="Failed to fetch claim")
    if not claim:
        raise HTTPException(status_code=404, detail="No claim found")
    return claim


@router.post("/leads/{lead_id}/claims")
async def lead_create_claim(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.json()
    control_no = body.get("control_no") or ""
    formation_state = body.get("formation_state") or ""
    fee_pct = body.get("fee_pct") or "10"
    fee_flat = body.get("fee_flat")  # Optional flat fee
    addendum_yes = bool(body.get("addendum_yes", False))
    entitled_business_name = body.get("entitled_business_name")  # Optional, defaults to owner_name
    entitled_business_same_as_owner = body.get("entitled_business_same_as_owner", True)

    try:
        result = create_claim_from_lead(
            db=db,
            lead_id=lead_id,
            control_no=control_no,
            formation_state=formation_state,
            fee_pct=fee_pct,
            addendum_yes=addendum_yes,
            user=None,
            entitled_business_name=entitled_business_name,
            entitled_business_same_as_owner=entitled_business_same_as_owner,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("lead_create_claim failed")
        raise HTTPException(status_code=500, detail="Failed to create claim")

    return result


@router.get("/claims", response_class=HTMLResponse)
def claims_list(
    request: Request,
    status: str = Query("", description="Filter by claim status"),
    db: Session = Depends(get_db),
):
    claims = (
        db.query(Claim)
        .order_by(Claim.created_at.desc())
        .all()
    )
    claim_rows = []
    for claim in claims:
        events = list_events_for_claim(db, claim.id)
        status_events = [e for e in events if e.get("state") in CLAIM_STATUS_VALUES]
        last_event = status_events[0] if status_events else None
        doc_count = db.query(ClaimDocument).filter(ClaimDocument.claim_id == claim.id).count()
        last_event_created_at = None
        if last_event:
            ts = last_event.get("created_at")
            last_event_created_at = ts if isinstance(ts, str) else ts.isoformat() if ts else None
        current_state = last_event["state"] if last_event else None
        
        # Query lead normally; enum now includes claim_created so no raw SQL fallback needed
        lead_owner = ""
        lead_status = ""
        if claim.lead_id:
            lead = db.query(Lead).filter(Lead.id == claim.lead_id).first()
            if lead:
                lead_owner = lead.owner_name or ""
                lead_status = str(lead.status) if getattr(lead, "status", None) else ""
        
        # Get client data
        client = claim.client
        fee_display = None
        if claim.fee_flat:
            fee_display = f"${claim.fee_flat:,.2f}"
        elif claim.fee_pct:
            fee_display = f"{claim.fee_pct}%"
        
        claim_rows.append(
            {
                "id": claim.id,
                "claim_slug": claim.claim_slug,
                "lead_id": claim.lead_id,
                "lead_owner": lead_owner,
                "lead_status": lead_status,
                "control_no": client.control_no if client else None,
                "formation_state": client.formation_state if client else None,
                "fee_pct": str(claim.fee_pct) if claim.fee_pct else None,
                "fee_flat": str(claim.fee_flat) if claim.fee_flat else None,
                "fee_display": fee_display,
                "addendum_yes": claim.addendum_yes,
                "output_dir": claim.output_dir,
                "created_at": claim.created_at,
                "last_event": last_event,
                "last_event_created_at": last_event_created_at,
                "current_state": current_state,
                "doc_count": doc_count,
            }
        )
    if status:
        claim_rows = [c for c in claim_rows if c["current_state"] == status]

    return templates.TemplateResponse(
        "claims.html",
        {
            "request": request,
            "claims": claim_rows,
            "claim_status_values": CLAIM_STATUS_VALUES,
            "status_filter": status,
        },
    )


@router.get("/claims/{claim_id}", response_class=HTMLResponse)
def claim_detail(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    
    # Get client and related data
    client = claim.client
    primary_contact = None
    secondary_contact = None
    check_address = claim.check_mailing_address
    
    if client:
        from models import ClientContact, SignerType
        contacts = db.query(ClientContact).filter(ClientContact.client_id == client.id).all()
        for contact in contacts:
            if contact.signer_type == SignerType.primary:
                primary_contact = contact
            elif contact.signer_type == SignerType.secondary:
                secondary_contact = contact
    
    # Get lead primary contact for reference
    lead_primary_contact = None
    if claim.lead:
        for c in claim.lead.contacts:
            if c.is_primary:
                lead_primary_contact = c
                break
    
    # Prepare lead primary contact data for JSON
    lead_primary_contact_json = {}
    if lead_primary_contact:
        lead_primary_contact_json = {
            "contact_name": lead_primary_contact.contact_name or "",
            "title": lead_primary_contact.title or "",
            "email": lead_primary_contact.email or "",
            "phone": lead_primary_contact.phone or "",
            "address_street": lead_primary_contact.address_street or "",
            "address_city": lead_primary_contact.address_city or "",
            "address_state": lead_primary_contact.address_state or "",
            "address_zipcode": lead_primary_contact.address_zipcode or "",
        }
    
    # Calculate totals from lead properties
    total_properties = 0
    total_amount = 0.0
    if claim.lead:
        from models import LeadProperty
        properties = db.query(LeadProperty).filter(LeadProperty.lead_id == claim.lead.id).all()
        total_properties = len(properties)
        for prop in properties:
            if prop.property_amount:
                total_amount += float(prop.property_amount)
    
    # Calculate CDR fee if fee structure is set
    cdr_fee = None
    if claim.fee_flat:
        cdr_fee = float(claim.fee_flat)
    elif claim.fee_pct and total_amount > 0:
        cdr_fee = float(total_amount) * (float(claim.fee_pct) / 100.0)
    
    # Update claim with calculated values if they're different
    if claim.total_properties != total_properties or claim.total_amount != total_amount or (cdr_fee and claim.cdr_fee != cdr_fee):
        claim.total_properties = total_properties
        claim.total_amount = total_amount
        if cdr_fee:
            claim.cdr_fee = cdr_fee
        db.commit()
    
    events = list_events_for_claim(db, claim.id)
    status_events = [e for e in events if e.get("state") in CLAIM_STATUS_VALUES]
    current_status = status_events[0]["state"] if status_events else None
    docs = list_documents_for_claim(db, claim.id)
    generated_docs = [d for d in docs if d["doc_type"] in ("agreement_generated", "authorization_generated")]
    package_docs = [d for d in docs if d["doc_type"] not in ("agreement_generated", "authorization_generated")]
    
    # Determine if check address is same as lead primary contact
    # Check if all address fields match and line2 is None (set when using lead contact)
    check_address_same_as_contact = False
    if check_address and lead_primary_contact:
        check_address_same_as_contact = (
            (check_address.street or "") == (lead_primary_contact.address_street or "") and
            (check_address.city or "") == (lead_primary_contact.address_city or "") and
            (check_address.state or "") == (lead_primary_contact.address_state or "") and
            (check_address.zip or "") == (lead_primary_contact.address_zipcode or "") and
            check_address.line2 is None
        )
    
    return templates.TemplateResponse(
        "claim_detail.html",
        {
            "request": request,
            "claim": claim,
            "client": client,
            "primary_contact": primary_contact,
            "secondary_contact": secondary_contact,
            "check_address": check_address,
            "lead_primary_contact": lead_primary_contact,
            "lead_primary_contact_json": json.dumps(lead_primary_contact_json),
            "check_address_same_as_contact": check_address_same_as_contact,
            "events": events,
            "current_status": current_status,
            "generated_docs": generated_docs,
            "package_docs": package_docs,
            "download_base": "",
            "claim_status_values": CLAIM_STATUS_VALUES,
        },
    )


@router.get("/claims/{claim_id}/events")
def claim_events(
    claim_id: int,
    db: Session = Depends(get_db),
):
    try:
        events = list_events_for_claim(db, claim_id)
    except Exception:
        logger.exception("claim_events failed")
        raise HTTPException(status_code=500, detail="Failed to fetch claim events")
    return {"events": events}


@router.get("/claims/{claim_id}/documents")
def claim_documents(
    claim_id: int,
    db: Session = Depends(get_db),
):
    try:
        docs = list_documents_for_claim(db, claim_id)
    except Exception:
        logger.exception("claim_documents failed")
        raise HTTPException(status_code=500, detail="Failed to fetch claim documents")
    # Add download URLs
    for d in docs:
        d["download_url"] = f"/claims/{claim_id}/documents/{d['id']}/download"
        d["preview_url"] = f"/claims/{claim_id}/documents/{d['id']}/download?inline=1"
    return {"documents": docs}


@router.get("/claims/{claim_id}/documents/{doc_id}/download")
def claim_document_download(
    claim_id: int,
    doc_id: int,
    inline: bool = Query(False),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(ClaimDocument)
        .filter(ClaimDocument.id == doc_id, ClaimDocument.claim_id == claim_id)
        .one_or_none()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(status_code=404, detail="File not found")
    media_type, _ = mimetypes.guess_type(doc.file_path)
    media_type = media_type or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path=doc.file_path,
        filename=doc.original_name or Path(doc.file_path).name,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{Path(doc.file_path).name}"'},
    )


@router.get("/claims/{claim_id}/files")
def claim_files(
    claim_id: int,
    type: str = Query("generated", regex="^(generated|package)$"),
    db: Session = Depends(get_db),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    base_dir = Path(claim.output_dir or "")
    target = base_dir / ("generated" if type == "generated" else "package")
    files = _list_files_in_dir(target)
    for f in files:
        f["download_url"] = f"/claims/{claim_id}/files/download?type={type}&name={f['name']}"
        f["preview_url"] = f"{f['download_url']}&inline=1"
    return {"files": files}


@router.get("/claims/{claim_id}/files/download")
def claim_file_download(
    claim_id: int,
    name: str = Query(...),
    type: str = Query("generated", regex="^(generated|package)$"),
    inline: bool = Query(False),
    db: Session = Depends(get_db),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    base_dir = Path(claim.output_dir or "")
    target = base_dir / ("generated" if type == "generated" else "package")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    file_path = target / name
    try:
        # prevent traversal
        file_path.resolve().relative_to(target.resolve())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media_type, _ = mimetypes.guess_type(str(file_path))
    media_type = media_type or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path=str(file_path),
        filename=name,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{name}"'},
    )


@router.delete("/claims/{claim_id}/files")
def claim_file_delete(
    claim_id: int,
    name: str = Query(...),
    type: str = Query("generated", regex="^(generated|package)$"),
    db: Session = Depends(get_db),
):
    from models import ClaimDocument
    
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    base_dir = Path(claim.output_dir or "")
    target = base_dir / ("generated" if type == "generated" else "package")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    file_path = target / name
    try:
        file_path.resolve().relative_to(target.resolve())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Find and delete the ClaimDocument record
    # Match by file_path for all file types - this is the most reliable way
    # Normalize paths to handle any path separator or absolute/relative differences
    file_path_absolute = str(file_path.resolve()).replace('\\', '/')
    file_path_relative = str(file_path).replace('\\', '/')
    
    # Get all documents for this claim to do flexible matching
    all_docs = db.query(ClaimDocument).filter(
        ClaimDocument.claim_id == claim.id
    ).all()
    
    doc = None
    for d in all_docs:
        if not d.file_path:
            continue
        # Normalize the stored path
        normalized_db_path = d.file_path.replace('\\', '/')
        
        # Try exact matches first (both absolute and relative)
        if normalized_db_path == file_path_absolute or normalized_db_path == file_path_relative:
            doc = d
            break
        
        # Try matching by resolving the stored path to absolute and comparing
        try:
            stored_absolute = str(Path(d.file_path).resolve()).replace('\\', '/')
            if stored_absolute == file_path_absolute:
                doc = d
                break
        except Exception:
            pass
        
        # Fallback: match by filename at the end of the path
        # This handles cases where paths are stored differently (relative vs absolute)
        # Extract just the filename from both paths for comparison
        db_filename = normalized_db_path.split('/')[-1].split('\\')[-1]
        target_filename = name
        
        if db_filename == target_filename:
            doc = d
            break
        
        # Also try if either path ends with the filename
        if normalized_db_path.endswith('/' + name) or normalized_db_path.endswith('\\' + name):
            doc = d
            break
        if normalized_db_path.endswith(name):
            doc = d
            break
    
    # Delete file from filesystem
    file_path.unlink(missing_ok=True)
    
    # Delete ClaimDocument record if found
    # Also delete any duplicate documents with same doc_type and original_name but different paths
    # This handles cases where duplicates were created (e.g., relative vs absolute paths)
    doc_type_for_event = None
    original_name_for_event = name
    docs_to_delete = []
    
    if doc:
        doc_type_for_event = doc.doc_type
        original_name_for_event = doc.original_name or name
        docs_to_delete.append(doc)
        
        # Find and delete duplicates - same doc_type and original_name but different file_path
        # This ensures we clean up any duplicate records that might exist
        duplicates = db.query(ClaimDocument).filter(
            ClaimDocument.claim_id == claim.id,
            ClaimDocument.doc_type == doc.doc_type,
            ClaimDocument.original_name == doc.original_name,
            ClaimDocument.id != doc.id
        ).all()
        
        if duplicates:
            docs_to_delete.extend(duplicates)
    
    # Delete all matched documents
    for d in docs_to_delete:
        db.delete(d)
    
    if docs_to_delete:
        db.flush()
        # Verify deletion only if there's an issue
        for d in docs_to_delete:
            still_exists = db.query(ClaimDocument).filter(ClaimDocument.id == d.id).first()
            if still_exists:
                logger.error(f"Document {d.id} still exists after delete and flush!")
    else:
        # Log warning if document not found - this shouldn't happen but helps debug
        logger.warning(f"ClaimDocument not found for deletion: claim_id={claim.id}, name={name}, type={type}")

    # Log deletion event with better categorization
    event_state = "generated_file_deleted" if type == "generated" else "package_file_deleted"
    event = ClaimEvent(
        claim_id=claim.id,
        state=event_state,
        payload=json.dumps({
            "file_type": type,
            "doc_type": doc_type_for_event,
            "name": original_name_for_event,
            "file_name": name
        }),
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()

    return {"deleted": True}


@router.post("/claims/{claim_id}/documents/upload")
async def claim_upload_document(
    claim_id: int,
    doc_type: str = Form(...),
    notes: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if not doc_type:
        raise HTTPException(status_code=400, detail="doc_type is required")
    if not file:
        raise HTTPException(status_code=400, detail="file is required")

    # Ensure output dir
    if not claim.output_dir:
        claim.output_dir = str(Path("scripts/pdf_output") / f"claim-{claim.id}")
    output_dir = Path(claim.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    package_dir = output_dir / "package"
    package_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    dest_path = package_dir / safe_name
    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # Normalize file_path to use forward slashes and resolve to absolute path for consistency
    normalized_file_path = str(dest_path.resolve()).replace('\\', '/')
    
    # Check for existing document with same doc_type and file_path (normalized)
    # This prevents duplicates from being created
    existing_doc = db.query(ClaimDocument).filter(
        ClaimDocument.claim_id == claim.id,
        ClaimDocument.doc_type == doc_type,
        ClaimDocument.file_path == normalized_file_path
    ).first()
    
    # Also check for relative path version
    if not existing_doc:
        relative_path = str(dest_path).replace('\\', '/')
        existing_doc = db.query(ClaimDocument).filter(
            ClaimDocument.claim_id == claim.id,
            ClaimDocument.doc_type == doc_type,
            ClaimDocument.file_path == relative_path
        ).first()
    
    # Also check by resolving stored paths
    if not existing_doc:
        all_same_type = db.query(ClaimDocument).filter(
            ClaimDocument.claim_id == claim.id,
            ClaimDocument.doc_type == doc_type
        ).all()
        for d in all_same_type:
            try:
                stored_resolved = str(Path(d.file_path).resolve()).replace('\\', '/')
                if stored_resolved == normalized_file_path:
                    existing_doc = d
                    break
            except Exception:
                pass
    
    if existing_doc:
        # Update existing document instead of creating duplicate
        existing_doc.file_path = normalized_file_path
        existing_doc.original_name = file.filename or safe_name
        if notes:
            existing_doc.notes = notes
        doc = existing_doc
    else:
        doc = ClaimDocument(
            claim_id=claim.id,
            doc_type=doc_type,
            original_name=file.filename or safe_name,
            file_path=normalized_file_path,
            notes=notes,
        )
        db.add(doc)

    # Log upload event with better categorization
    upload_event = ClaimEvent(
        claim_id=claim.id,
        state="package_file_uploaded",
        payload=json.dumps({
            "doc_type": doc_type,
            "name": file.filename or safe_name,
            "file_name": safe_name
        }),
        created_at=datetime.utcnow(),
    )
    db.add(upload_event)
    db.commit()

    return {
        "id": doc.id,
        "doc_type": doc.doc_type,
        "original_name": doc.original_name,
        "file_path": doc.file_path,
        "notes": doc.notes,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.post("/claims/{claim_id}/agreements/generate")
async def claim_generate_agreements(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.json()
    control_no = body.get("control_no") or ""
    formation_state = body.get("formation_state") or ""
    fee_pct = body.get("fee_pct")  # Optional, defaults to 10 in service
    fee_flat = body.get("fee_flat")  # Optional flat fee
    addendum_yes = bool(body.get("addendum_yes", False))

    if not control_no or not formation_state:
        raise HTTPException(status_code=400, detail="control_no and formation_state are required")
    
    if not fee_pct and not fee_flat:
        fee_pct = "10"  # Default to 10%

    try:
        result = generate_agreements_for_claim(
            db=db,
            claim_id=claim_id,
            control_no=control_no,
            formation_state=formation_state,
            fee_pct=fee_pct or "10",
            addendum_yes=addendum_yes,
            user=None,
            fee_flat=fee_flat,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("claim_generate_agreements failed")
        raise HTTPException(status_code=500, detail="Failed to generate agreements")

    return result


@router.post("/claims/{claim_id}/client-info")
async def claim_save_client_info(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Save client and claim information including signers and mailing address."""
    from models import Client, ClientContact, ClientMailingAddress, SignerType, LeadContact
    
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    
    if not claim.lead:
        raise HTTPException(status_code=400, detail="Lead not found for claim")
    
    body = await request.json()
    
    # Get or create client
    client = claim.client
    if not client:
        client = Client(
            entitled_business_name=body.get("entitled_business_name", ""),
            formation_state=None,
            control_no=None,
        )
        db.add(client)
        db.flush()
        claim.client_id = client.id
        db.flush()
    
    # Update client
    client.entitled_business_name = body.get("entitled_business_name", "")
    if "control_no" in body:
        client.control_no = body.get("control_no") or None
    if "formation_state" in body:
        client.formation_state = body.get("formation_state") or None
    
    # Update claim
    claim.entitled_business_name = body.get("entitled_business_name", "")
    claim.entitled_business_same_as_owner = body.get("entitled_business_same_as_owner", True)
    
    # Update fee structure
    fee_type = body.get("fee_type", "percentage")
    if fee_type == "flat":
        fee_flat_val = body.get("fee_flat")
        if fee_flat_val:
            claim.fee_flat = float(fee_flat_val)
            claim.fee_pct = None
        else:
            # If flat fee type but no value, default to percentage with 10%
            claim.fee_pct = 10.0
            claim.fee_flat = None
    else:
        fee_pct_val = body.get("fee_pct", "10")
        claim.fee_pct = float(fee_pct_val) if fee_pct_val else 10.0
        claim.fee_flat = None
    
    # Update addendum
    if "addendum_yes" in body:
        claim.addendum_yes = body.get("addendum_yes", False)
    
    # Recalculate CDR fee if needed
    if claim.lead:
        from models import LeadProperty
        properties = db.query(LeadProperty).filter(LeadProperty.lead_id == claim.lead.id).all()
        total_amount = sum(float(p.property_amount) if p.property_amount else 0.0 for p in properties)
        if claim.fee_flat:
            claim.cdr_fee = float(claim.fee_flat)
        elif claim.fee_pct and total_amount > 0:
            claim.cdr_fee = round(total_amount * (float(claim.fee_pct) / 100.0), 2)
    
    # Get primary lead contact for reference
    lead_primary_contact = None
    for c in claim.lead.contacts:
        if c.is_primary:
            lead_primary_contact = c
            break
    
    # Handle primary signer
    primary_signer_same = body.get("primary_signer_same_as_contact", False)
    primary_signer_data = body.get("primary_signer")
    
    if primary_signer_same and lead_primary_contact:
        # Use lead contact - find or create client contact
        primary_client_contact = (
            db.query(ClientContact)
            .filter(ClientContact.client_id == client.id, ClientContact.signer_type == SignerType.primary)
            .first()
        )
        if not primary_client_contact:
            name_parts = (lead_primary_contact.contact_name or "").strip().split(" ", 1)
            first_name = name_parts[0] if name_parts else ""
            last_name = name_parts[1] if len(name_parts) > 1 else ""
            primary_client_contact = ClientContact(
                client_id=client.id,
                lead_contact_id=lead_primary_contact.id,
                signer_type=SignerType.primary,
                first_name=first_name,
                last_name=last_name,
                title=lead_primary_contact.title,
                email=lead_primary_contact.email,
                phone=lead_primary_contact.phone,
            )
            db.add(primary_client_contact)
        else:
            # Update existing
            name_parts = (lead_primary_contact.contact_name or "").strip().split(" ", 1)
            primary_client_contact.first_name = name_parts[0] if name_parts else ""
            primary_client_contact.last_name = name_parts[1] if len(name_parts) > 1 else ""
            primary_client_contact.title = lead_primary_contact.title
            primary_client_contact.email = lead_primary_contact.email
            primary_client_contact.phone = lead_primary_contact.phone
            primary_client_contact.lead_contact_id = lead_primary_contact.id
    elif primary_signer_data:
        # Use provided data
        primary_client_contact = (
            db.query(ClientContact)
            .filter(ClientContact.client_id == client.id, ClientContact.signer_type == SignerType.primary)
            .first()
        )
        if not primary_client_contact:
            primary_client_contact = ClientContact(
                client_id=client.id,
                signer_type=SignerType.primary,
                first_name=primary_signer_data.get("first_name", ""),
                last_name=primary_signer_data.get("last_name", ""),
                title=primary_signer_data.get("title"),
                email=primary_signer_data.get("email"),
                phone=primary_signer_data.get("phone"),
            )
            db.add(primary_client_contact)
        else:
            primary_client_contact.first_name = primary_signer_data.get("first_name", "")
            primary_client_contact.last_name = primary_signer_data.get("last_name", "")
            primary_client_contact.title = primary_signer_data.get("title")
            primary_client_contact.email = primary_signer_data.get("email")
            primary_client_contact.phone = primary_signer_data.get("phone")
            primary_client_contact.lead_contact_id = None
    
    # Handle secondary signer (optional)
    secondary_signer_enabled = body.get("secondary_signer_enabled", False)
    secondary_signer_data = body.get("secondary_signer")
    
    # Check if secondary signer exists
    existing_secondary = (
        db.query(ClientContact)
        .filter(ClientContact.client_id == client.id, ClientContact.signer_type == SignerType.secondary)
        .first()
    )
    
    if secondary_signer_enabled and secondary_signer_data and (secondary_signer_data.get("first_name") or secondary_signer_data.get("last_name")):
        if not existing_secondary:
            secondary_client_contact = ClientContact(
                client_id=client.id,
                signer_type=SignerType.secondary,
                first_name=secondary_signer_data.get("first_name", ""),
                last_name=secondary_signer_data.get("last_name", ""),
                title=secondary_signer_data.get("title"),
                email=secondary_signer_data.get("email"),
                phone=secondary_signer_data.get("phone"),
            )
            db.add(secondary_client_contact)
        else:
            existing_secondary.first_name = secondary_signer_data.get("first_name", "")
            existing_secondary.last_name = secondary_signer_data.get("last_name", "")
            existing_secondary.title = secondary_signer_data.get("title")
            existing_secondary.email = secondary_signer_data.get("email")
            existing_secondary.phone = secondary_signer_data.get("phone")
    elif not secondary_signer_enabled and existing_secondary:
        # Remove secondary signer if disabled
        db.delete(existing_secondary)
    
    # Handle check mailing address
    check_address_same = body.get("check_address_same_as_contact", False)
    check_address_data = body.get("check_address")
    
    # Get or create mailing address
    check_address = (
        db.query(ClientMailingAddress)
        .filter(ClientMailingAddress.client_id == client.id)
        .first()
    )
    
    if check_address_same and lead_primary_contact:
        # Use lead contact address - update existing or create new
        if not check_address:
            check_address = ClientMailingAddress(
                client_id=client.id,
                street=lead_primary_contact.address_street or "",
                line2=None,
                city=lead_primary_contact.address_city or "",
                state=lead_primary_contact.address_state or "",
                zip=lead_primary_contact.address_zipcode or "",
            )
            db.add(check_address)
            db.flush()
        else:
            # Update existing address with lead contact address
            check_address.street = lead_primary_contact.address_street or ""
            check_address.city = lead_primary_contact.address_city or ""
            check_address.state = lead_primary_contact.address_state or ""
            check_address.zip = lead_primary_contact.address_zipcode or ""
            check_address.line2 = None
        claim.check_mailing_address_id = check_address.id
    elif check_address_data:
        # Use provided address - update existing or create new
        if not check_address:
            check_address = ClientMailingAddress(
                client_id=client.id,
                street=check_address_data.get("street", ""),
                line2=check_address_data.get("line2"),
                city=check_address_data.get("city", ""),
                state=check_address_data.get("state", ""),
                zip=check_address_data.get("zip", ""),
            )
            db.add(check_address)
            db.flush()
        else:
            # Update existing address with provided data
            check_address.street = check_address_data.get("street", "")
            check_address.line2 = check_address_data.get("line2")
            check_address.city = check_address_data.get("city", "")
            check_address.state = check_address_data.get("state", "")
            check_address.zip = check_address_data.get("zip", "")
        claim.check_mailing_address_id = check_address.id
    
    # Record event for client/claim data save
    primary_signer_same = body.get("primary_signer_same_as_contact", False)
    check_address_same = body.get("check_address_same_as_contact", False)
    save_event_payload = {
        "entitled_business_name": claim.entitled_business_name,
        "control_no": client.control_no,
        "formation_state": client.formation_state,
        "fee_type": fee_type,
        "fee_pct": str(claim.fee_pct) if claim.fee_pct else None,
        "fee_flat": str(claim.fee_flat) if claim.fee_flat else None,
        "addendum_yes": claim.addendum_yes,
        "primary_signer_same_as_contact": primary_signer_same,
        "check_address_same_as_contact": check_address_same,
    }
    save_event = ClaimEvent(
        claim_id=claim.id,
        state="client_claim_data_saved",
        payload=json.dumps(save_event_payload),
        created_at=datetime.utcnow(),
    )
    db.add(save_event)
    db.commit()
    
    return {"success": True, "message": "Client and claim information saved"}


@router.post("/claims/{claim_id}/status")
async def claim_set_status(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.json()
    state = body.get("state")
    if not state:
        raise HTTPException(status_code=400, detail="state is required")
    if state not in CLAIM_STATUS_VALUES:
        raise HTTPException(status_code=400, detail="invalid state")

    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Record event
    event = ClaimEvent(
        claim_id=claim.id,
        state=state,
        payload=json.dumps({"status": state}),
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()

    return {
        "id": event.id,
        "state": event.state,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
