# main.py
from datetime import datetime, timezone
from io import BytesIO
from decimal import Decimal, InvalidOperation
from typing import Any
from pathlib import Path
import json
import re

from fastapi import FastAPI, Depends, Request, Form, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, cast, String, update
from markupsafe import Markup, escape

from db import Base, SessionLocal, engine
from models import (
    PropertyView,
    BusinessLead,
    LeadStatus,
    LeadContact,
    LeadAttempt,
    LeadComment,
    ContactChannel,
    OwnerType,
    BusinessOwnerStatus,
    OwnerSize,
    IndividualOwnerStatus,
    ContactType,
    ScheduledEmail,
    ScheduledEmailStatus,
    PrintLog,
)

from letters import (
    LetterGenerationError,
    get_property_for_lead,
    render_letter_pdf,
)
from gpt_api import fetch_entity_intelligence, GPTConfigError, GPTServiceError
from email_service import (
    prep_contact_email,
    send_email,
    resolve_profile,
    embed_profile_marker,
    extract_profile_marker,
    PROFILE_REGISTRY,
)
from email_scheduler import start_scheduler, stop_scheduler

from fastapi.templating import Jinja2Templates


Base.metadata.create_all(
    bind=engine,
    tables=[
        BusinessLead.__table__,
        LeadContact.__table__,
        LeadAttempt.__table__,
        LeadComment.__table__,
        ScheduledEmail.__table__,
        PrintLog.__table__,
    ],
)

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def bootstrap_assignment_flags():
    _sync_existing_property_assignments()
    start_scheduler()


@app.on_event("shutdown")
def shutdown_scheduler():
    stop_scheduler()


def format_currency(value):
    if value is None or value == "":
        return "—"

    if isinstance(value, Decimal):
        decimal_value = value
    else:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return str(value)

    return f"${decimal_value:,.2f}"


templates.env.filters["currency"] = format_currency



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

PAGE_SIZE = 20
PROPERTY_MIN_AMOUNT = Decimal("10000")
PROPERTY_AMOUNT_FILTER = PropertyView.propertyamount >= PROPERTY_MIN_AMOUNT
PROPERTY_ORDERING = (
    PropertyView.propertyamount.desc(),
    PropertyView.raw_hash.asc(),
)

PHONE_SCRIPTS_DIR = Path("templates") / "phone"
PHONE_SCRIPT_SOURCES = [
    ("registered_agent", "Registered Agent", PHONE_SCRIPTS_DIR / "registered_agent.html"),
    ("decision_maker", "Decision Maker", PHONE_SCRIPTS_DIR / "decision_maker.html"),
    ("gatekeeper_contact", "Gatekeeper Contact Discovery", PHONE_SCRIPTS_DIR / "gatekeeper_contact_discovery_call.html"),
]

STYLE_TAG_RE = re.compile(r"<style.*?>.*?</style>", re.S | re.I)
SCRIPT_TAG_RE = re.compile(r"<script.*?>.*?</script>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\n\s*\n+", re.S)
HTML_SNIPPET_RE = re.compile(
    r"<\s*(?:!doctype|html|head|body|section|div|article|main|header|footer|p|h[1-6]|ul|ol|li|table|tr|td)\b",
    re.I,
)


def _plain_text_to_html(text: str) -> str:
    paragraphs = [para.strip() for para in text.split("\n\n") if para.strip()]
    if not paragraphs:
        return str(Markup("<p>No script available.</p>"))
    
    html_parts = []
    for para in paragraphs:
        lines = [line.strip() for line in para.splitlines()]
        escaped_lines = [escape(line) for line in lines if line]
        if escaped_lines:
            html_parts.append(f"<p>{'<br>'.join(escaped_lines)}</p>")
    
    if not html_parts:
        html_parts.append("<p>No script available.</p>")
    
    return str(Markup("".join(html_parts)))


def _looks_like_html(text: str) -> bool:
    snippet = text.strip()
    if not snippet:
        return False

    lower = snippet.lower()
    if lower.startswith("<!doctype") or lower.startswith("<html") or "<body" in lower:
        return True

    return bool(HTML_SNIPPET_RE.search(lower))


def _extract_body_fragment(text: str) -> str:
    lower = text.lower()
    body_start = lower.find("<body")
    if body_start != -1:
        start_tag_end = text.find(">", body_start)
        body_end = lower.rfind("</body>")
        if start_tag_end != -1 and body_end != -1:
            return text[start_tag_end + 1 : body_end]
    return text


def _strip_tags_to_text(html_text: str) -> str:
    stripped = TAG_RE.sub("\n", html_text)
    stripped = WHITESPACE_RE.sub("\n\n", stripped)
    return stripped.strip()


def _prepare_script_content(raw_text: str) -> tuple[str, str]:
    if not raw_text:
        return str(Markup("<p>No script available.</p>")), ""
    
    if _looks_like_html(raw_text):
        content = STYLE_TAG_RE.sub("", raw_text)
        content = SCRIPT_TAG_RE.sub("", content)
        content = _extract_body_fragment(content).strip()
        if not content:
            return str(Markup("<p>No script available.</p>")), ""
        plain = _strip_tags_to_text(content)
        return str(Markup(content)), plain
    
    plain_text = raw_text.strip()
    html_value = _plain_text_to_html(plain_text)
    return html_value, plain_text


def _load_phone_scripts():
    scripts = []
    for key, label, path in PHONE_SCRIPT_SOURCES:
        try:
            raw_text = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            raw_text = ""
        else:
            raw_text = raw_text.replace("\r\n", "\n")
        html_value, plain_value = _prepare_script_content(raw_text)
        scripts.append(
            {
                "key": key,
                "label": label,
                "text": plain_value,
                "html": html_value,
            }
        )
    return scripts


PHONE_SCRIPTS = _load_phone_scripts()
PHONE_SCRIPTS_JSON = json.dumps(PHONE_SCRIPTS)

PROFILE_UI_DATA = {
    key: {
        "key": key,
        "label": profile.get("label") or key.title(),
        "firstName": profile.get("first_name") or profile.get("label") or key.title(),
        "lastName": profile.get("last_name") or "",
        "fullName": profile.get("full_name") or profile.get("label") or key.title(),
        "email": profile.get("from_email") or "",
        "phone": profile.get("phone") or "",
    }
    for key, profile in PROFILE_REGISTRY.items()
}
PROFILE_UI_JSON = json.dumps(PROFILE_UI_DATA)
templates.env.globals["profile_registry_json"] = PROFILE_UI_JSON


def _mark_property_assigned(db: Session, property_raw_hash: str | None, property_id: str | None):
    _set_property_assignment(db, property_raw_hash, property_id, True)


def _set_property_assignment(
    db: Session, property_raw_hash: str | None, property_id: str | None, assigned: bool = True
):
    update_stmt = None
    if property_raw_hash:
        update_stmt = (
            update(PropertyView)
            .where(PropertyView.raw_hash == property_raw_hash)
            .values(assigned_to_lead=assigned)
        )
    elif property_id:
        update_stmt = (
            update(PropertyView)
            .where(PropertyView.propertyid == property_id)
            .values(assigned_to_lead=assigned)
        )

    if update_stmt is not None:
        db.execute(update_stmt)


def _unmark_property_if_unused(db: Session, property_raw_hash: str | None, property_id: str | None):
    if property_raw_hash:
        still_used = db.scalar(
            select(BusinessLead.id)
            .where(BusinessLead.property_raw_hash == property_raw_hash)
            .limit(1)
        )
        if not still_used:
            _set_property_assignment(db, property_raw_hash, None, False)
            return

    if property_id:
        still_used = db.scalar(
            select(BusinessLead.id)
            .where(BusinessLead.property_id == property_id)
            .limit(1)
        )
        if not still_used:
            _set_property_assignment(db, None, property_id, False)


def _sync_existing_property_assignments():
    db = SessionLocal()
    try:
        raw_hashes = {
            value
            for value in db.scalars(
                select(BusinessLead.property_raw_hash).where(
                    BusinessLead.property_raw_hash.is_not(None)
                )
            ).all()
            if value
        }
        if raw_hashes:
            db.execute(
                update(PropertyView)
                .where(PropertyView.raw_hash.in_(tuple(raw_hashes)))
                .values(assigned_to_lead=True)
            )

        property_ids = {
            value
            for value in db.scalars(
                select(BusinessLead.property_id).where(
                    BusinessLead.property_id.is_not(None)
                )
            ).all()
            if value
        }
        if property_ids:
            db.execute(
                update(PropertyView)
                .where(PropertyView.propertyid.in_(tuple(property_ids)))
                .values(assigned_to_lead=True)
            )

        if raw_hashes or property_ids:
            db.commit()
    finally:
        db.close()


def _get_property_by_id(db: Session, property_id: str) -> PropertyView | None:
    return db.scalar(
        select(PropertyView)
        .where(PROPERTY_AMOUNT_FILTER)
        .where(PropertyView.propertyid == property_id)
    )


def _get_property_by_order(db: Session, order_id: int) -> PropertyView | None:
    raw_hash = _get_raw_hash_for_order(db, order_id)
    if not raw_hash:
        return None
    return _get_property_by_raw_hash(db, raw_hash)


def _get_property_by_raw_hash(db: Session, raw_hash: str) -> PropertyView | None:
    return db.scalar(
        select(PropertyView)
        .where(PROPERTY_AMOUNT_FILTER)
        .where(PropertyView.raw_hash == raw_hash)
    )


def _ranked_navigation_row(db: Session, raw_hash: str):
    ranked = (
        select(
            PropertyView.raw_hash.label("raw_hash"),
            func.row_number().over(order_by=PROPERTY_ORDERING).label("order_id"),
            func.lag(PropertyView.raw_hash).over(order_by=PROPERTY_ORDERING).label("prev_hash"),
            func.lead(PropertyView.raw_hash).over(order_by=PROPERTY_ORDERING).label("next_hash"),
        )
        .where(PROPERTY_AMOUNT_FILTER)
        .subquery()
    )
    return db.execute(
        select(
            ranked.c.order_id,
            ranked.c.prev_hash,
            ranked.c.next_hash,
        ).where(ranked.c.raw_hash == raw_hash)
    ).one_or_none()


def _get_property_details_for_lead(db: Session, lead: BusinessLead) -> PropertyView | None:
    if lead.property_raw_hash:
        prop = _get_property_by_raw_hash(db, lead.property_raw_hash)
        if prop:
            return prop
    if lead.property_id:
        return _get_property_by_id(db, lead.property_id)
    return None


def _build_phone_script_context(
    owner_name: str | None,
    property_id: str | None,
    property_amount,
    property_details: PropertyView | None,
):
    amount_value = None
    if property_details and property_details.propertyamount not in (None, ""):
        amount_value = property_details.propertyamount
    elif property_amount not in (None, ""):
        amount_value = property_amount

    formatted_amount = format_currency(amount_value) if amount_value not in (None, "") else ""

    return {
        "OwnerName": owner_name or "",
        "PropertyID": property_id or "",
        "PropertyAmount": formatted_amount,
        "PropertyAmountValue": str(amount_value) if amount_value not in (None, "") else "",
        "HolderName": (property_details.holdername if property_details else "") or "",
        "ReportYear": (property_details.reportyear if property_details else "") or "",
        "PropertyType": (property_details.propertytypedescription if property_details else "") or "",
    }


def _serialize_print_log(log: PrintLog) -> dict[str, Any]:
    contact = log.contact
    address_lines: list[str] = []
    if contact:
        if contact.address_street:
            address_lines.append(contact.address_street.strip())
        city = (contact.address_city or "").strip()
        state = (contact.address_state or "").strip()
        zipcode = (contact.address_zipcode or "").strip()
        if city or state:
            line = ", ".join(part for part in (city, state) if part)
            if zipcode:
                line = f"{line} {zipcode}".strip()
            address_lines.append(line)
        elif zipcode:
            address_lines.append(zipcode)

    return {
        "id": log.id,
        "leadId": log.lead_id,
        "contactId": log.contact_id,
        "contactName": contact.contact_name if contact else "",
        "contactTitle": contact.title if contact else "",
        "addressLines": [line for line in address_lines if line],
        "filename": log.filename,
        "filePath": log.file_path,
        "printedAt": log.printed_at.isoformat() if log.printed_at else None,
        "mailed": log.mailed,
        "mailedAt": log.mailed_at.isoformat() if log.mailed_at else None,
        "attemptId": log.attempt_id,
    }


def _get_print_logs_for_lead(db: Session, lead_id: int):
    result = db.execute(
        select(PrintLog)
        .where(PrintLog.lead_id == lead_id)
        .order_by(PrintLog.printed_at.desc())
    )
    return result.scalars().all()


def _property_navigation_info(db: Session, raw_hash: str):
    nav_row = _ranked_navigation_row(db, raw_hash)
    if not nav_row:
        return {
            "order_id": None,
            "prev_order_id": None,
            "next_order_id": None,
            "prev_hash": None,
            "next_hash": None,
        }

    order_id = nav_row.order_id
    prev_hash = nav_row.prev_hash
    next_hash = nav_row.next_hash

    return {
        "order_id": order_id,
        "prev_order_id": order_id - 1 if prev_hash else None,
        "next_order_id": order_id + 1 if next_hash else None,
        "prev_hash": prev_hash,
        "next_hash": next_hash,
    }


def _get_raw_hash_for_order(db: Session, order_id: int) -> str | None:
    ranked = (
        select(
            PropertyView.raw_hash.label("raw_hash"),
            func.row_number().over(order_by=PROPERTY_ORDERING).label("order_id"),
        )
        .where(PROPERTY_AMOUNT_FILTER)
        .subquery()
    )
    return db.scalar(
        select(ranked.c.raw_hash).where(ranked.c.order_id == order_id)
    )


def _build_gpt_payload(lead: BusinessLead, prop: PropertyView) -> dict[str, Any]:
    report_year_value = None
    if getattr(prop, "reportyear", None):
        try:
            report_year_value = int(str(prop.reportyear))
        except (TypeError, ValueError):
            report_year_value = None

    return {
        "business_name": lead.owner_name or prop.ownername or "",
        "property_state": prop.ownerstate or "",
        "holder_name_on_record": prop.holdername,
        "last_activity_date": prop.lastactivitydate,
        "property_report_year": report_year_value,
    }

@app.get("/", response_class=HTMLResponse)
@app.get("/properties", response_class=HTMLResponse)
def list_properties(
    request: Request,
    page: int = 1,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    if page < 1:
        page = 1

    filters = [PROPERTY_AMOUNT_FILTER]

    if q:
        pattern = f"%{q}%"
        prop_id_text = cast(PropertyView.propertyid, String)
        filters.append(
            or_(
                prop_id_text.ilike(pattern),
                PropertyView.ownername.ilike(pattern),
            )
        )

    count_stmt = (
        select(func.count())
        .select_from(PropertyView)
        .where(*filters)
    )

    ranked_stmt = (
        select(
            PropertyView.raw_hash.label("raw_hash"),
            PropertyView.propertyid.label("propertyid"),
            PropertyView.ownername.label("ownername"),
            PropertyView.propertyamount.label("propertyamount"),
            PropertyView.assigned_to_lead.label("assigned_to_lead"),
            func.row_number().over(order_by=PROPERTY_ORDERING).label("order_id"),
        )
        .where(*filters)
    )

    ranked_subq = ranked_stmt.subquery()
    stmt = (
        select(ranked_subq)
        .order_by(ranked_subq.c.order_id)
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )

    rows_result = db.execute(stmt).mappings().all()
    rows = [dict(row) for row in rows_result]
    total = db.scalar(count_stmt) or 0

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1

    return templates.TemplateResponse(
        "properties.html",
        {
            "request": request,
            "properties": rows,
            "page": page,
            "total_pages": total_pages,
            "q": q or "",
            "total": total,
        },
    )


@app.get(
    "/properties/{property_id}",
    response_class=HTMLResponse,
)
def property_detail(
    request: Request,
    property_id: str,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_id(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop.raw_hash)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.assigned_to_lead

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"] if show_navigation else None,
            "next_order_id": nav["next_order_id"] if show_navigation else None,
            "prev_raw_hash": nav["prev_hash"] if show_navigation else None,
            "next_raw_hash": nav["next_hash"] if show_navigation else None,
            "show_navigation": show_navigation,
            "show_add_to_lead": show_add_to_lead,
        },
    )

@app.get("/leads/new_from_property", response_class=HTMLResponse)
def new_lead_from_property(
    request: Request,
    property_id: str,
    db: Session = Depends(get_db),
):
    # 1) Ensure we actually got a non-empty property_id
    if not property_id:
        raise HTTPException(status_code=400, detail="property_id query parameter is required")

    # 2) Fetch row from the view using propertyid as PK
    prop = _get_property_by_id(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail=f"Property '{property_id}' not found in view")

    if prop.assigned_to_lead:
        existing_lead = db.scalar(
            select(BusinessLead).where(
                or_(
                    BusinessLead.property_raw_hash == prop.raw_hash,
                    BusinessLead.property_id == prop.propertyid,
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

    # 3) Pass the 3 fields to the template
    phone_script_context = _build_phone_script_context(
        prop.ownername if prop else None,
        prop.propertyid if prop else None,
        prop.propertyamount if prop else None,
        prop,
    )

    return templates.TemplateResponse(
        "lead_form.html",
        {
            "request": request,
            "lead": None,
            "mode": "create",
            "property_id": prop.propertyid,          # view column
            "owner_name": prop.ownername,           # view column
            "property_amount": prop.propertyamount, # view column
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
            "property_raw_hash": getattr(prop, "raw_hash", None),
            "can_generate_letters": False,
            "phone_scripts": PHONE_SCRIPTS,
            "phone_scripts_json": PHONE_SCRIPTS_JSON,
            "phone_script_context_json": json.dumps(phone_script_context, default=str),
            "print_logs_json": json.dumps([], default=str),
        },
    )


@app.get("/api/properties/{property_id}")
def property_detail_json(
    property_id: str,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_id(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    column_names = prop.__table__.columns.keys()
    data = {column: getattr(prop, column) for column in column_names}

    nav = _property_navigation_info(db, prop.raw_hash)

    return JSONResponse(
        {
            "property": data,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"],
            "next_order_id": nav["next_order_id"],
            "prev_raw_hash": nav["prev_hash"],
            "next_raw_hash": nav["next_hash"],
        }
    )


@app.get("/properties/by_hash/{raw_hash}", response_class=HTMLResponse)
def property_detail_by_hash(
    request: Request,
    raw_hash: str,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_raw_hash(db, raw_hash)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop.raw_hash)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.assigned_to_lead

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"] if show_navigation else None,
            "next_order_id": nav["next_order_id"] if show_navigation else None,
            "prev_raw_hash": nav["prev_hash"] if show_navigation else None,
            "next_raw_hash": nav["next_hash"] if show_navigation else None,
            "show_navigation": show_navigation,
            "show_add_to_lead": show_add_to_lead,
        },
    )


@app.get("/properties/by_order/{order_id}", response_class=HTMLResponse)
def property_detail_by_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_order(db, order_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop.raw_hash)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.assigned_to_lead

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"] if show_navigation else None,
            "next_order_id": nav["next_order_id"] if show_navigation else None,
            "prev_raw_hash": nav["prev_hash"] if show_navigation else None,
            "next_raw_hash": nav["next_hash"] if show_navigation else None,
            "show_navigation": show_navigation,
            "show_add_to_lead": show_add_to_lead,
        },
    )


@app.get("/api/properties/by_order/{order_id}")
def property_detail_json_by_order(
    order_id: int,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_order(db, order_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    column_names = prop.__table__.columns.keys()
    data = {column: getattr(prop, column) for column in column_names}

    nav = _property_navigation_info(db, prop.raw_hash)

    return JSONResponse(
        {
            "property": data,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"],
            "next_order_id": nav["next_order_id"],
            "prev_raw_hash": nav["prev_hash"],
            "next_raw_hash": nav["next_hash"],
        }
    )


@app.post("/leads/create")
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
    if owner_type == OwnerType.business:
        individual_owner_status = None
        if not business_owner_status:
            business_owner_status = BusinessOwnerStatus.active
        if not owner_size:
            owner_size = OwnerSize.corporate
        if business_owner_status not in (
            BusinessOwnerStatus.acquired_or_merged,
            BusinessOwnerStatus.active_renamed,
        ):
            new_business_name = None
        else:
            if not new_business_name or not new_business_name.strip():
                raise HTTPException(
                    status_code=400,
                    detail="New owner name is required when status is acquired_or_merged or active_renamed.",
                )
    else:
        business_owner_status = None
        owner_size = None
        new_business_name = None
        if not individual_owner_status:
            individual_owner_status = IndividualOwnerStatus.alive

    lead = BusinessLead(
        property_id=property_id,
        owner_name=owner_name,
        property_amount=property_amount,
        status=status,
        notes=notes,
        owner_type=owner_type,
        business_owner_status=business_owner_status,
        owner_size=owner_size,
        new_business_name=new_business_name,
        individual_owner_status=individual_owner_status,
        property_raw_hash=property_raw_hash,
    )
    db.add(lead)
    _mark_property_assigned(db, property_raw_hash, property_id)
    db.commit()
    db.refresh(lead)
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)

@app.get("/leads", response_class=HTMLResponse)
def list_leads(
    request: Request,
    page: int = 1,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    if page < 1:
        page = 1

    stmt = select(BusinessLead)
    count_stmt = select(func.count()).select_from(BusinessLead)

    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                BusinessLead.property_id.ilike(pattern),
                BusinessLead.owner_name.ilike(pattern)
            )
        )
        count_stmt = count_stmt.where(
            or_(
                BusinessLead.property_id.ilike(pattern),
                BusinessLead.owner_name.ilike(pattern)
            )
        )

    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(BusinessLead.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    leads = db.scalars(stmt).all()

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1

    return templates.TemplateResponse(
        "leads.html",
        {
            "request": request,
            "leads": leads,
            "page": page,
            "total_pages": total_pages,
            "q": q or "",
            "total": total,
        },
    )


@app.get("/leads/{lead_id}/entity-intel")
async def lead_entity_intelligence(
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    prop: PropertyView | None = None
    if lead.property_raw_hash:
        prop = _get_property_by_raw_hash(db, lead.property_raw_hash)

    if not prop and lead.property_id:
        prop = _get_property_by_id(db, lead.property_id)

    if not prop:
        raise HTTPException(
            status_code=404,
            detail="Linked property record not found for this lead.",
        )

    payload = _build_gpt_payload(lead, prop)

    try:
        analysis = await run_in_threadpool(fetch_entity_intelligence, payload)
    except GPTConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GPTServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"input": payload, "analysis": analysis}


@app.get("/leads/{lead_id}/edit", response_class=HTMLResponse)
def edit_lead(
    request: Request,
    lead_id: int,
    edit_contact_id: int | None = None,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

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

    property_details = _get_property_details_for_lead(db, lead)
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

    print_logs = _get_print_logs_for_lead(db, lead.id)
    print_logs_json = json.dumps(
        [_serialize_print_log(log) for log in print_logs],
        default=str,
    )

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
        },
    )


@app.post("/leads/{lead_id}/update")
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
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if owner_type == OwnerType.business:
        individual_owner_status = None
        if not business_owner_status:
            business_owner_status = BusinessOwnerStatus.active
        if not owner_size:
            owner_size = OwnerSize.corporate
        if business_owner_status not in (
            BusinessOwnerStatus.acquired_or_merged,
            BusinessOwnerStatus.active_renamed,
        ):
            new_business_name = None
        else:
            if not new_business_name or not new_business_name.strip():
                raise HTTPException(
                    status_code=400,
                    detail="New owner name is required when status is acquired_or_merged or active_renamed.",
                )
    else:
        business_owner_status = None
        owner_size = None
        if not individual_owner_status:
            individual_owner_status = IndividualOwnerStatus.alive
        new_business_name = None

    lead.property_id = property_id
    lead.owner_name = owner_name
    lead.property_amount = property_amount
    lead.status = status
    lead.notes = notes
    lead.owner_type = owner_type
    lead.business_owner_status = business_owner_status
    lead.owner_size = owner_size
    lead.new_business_name = new_business_name
    lead.individual_owner_status = individual_owner_status
    lead.property_raw_hash = property_raw_hash

    lead.updated_at = datetime.utcnow()

    _mark_property_assigned(db, property_raw_hash, property_id)
    db.commit()
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)

@app.post("/leads/{lead_id}/delete")
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    property_raw_hash = lead.property_raw_hash
    property_id = lead.property_id
    
    db.delete(lead)
    db.flush()
    _unmark_property_if_unused(db, property_raw_hash, property_id)
    db.commit()
    
    return RedirectResponse(url="/leads", status_code=303)


# ---------- CONTACTS FOR A LEAD ----------

@app.get("/leads/{lead_id}/contacts", response_class=HTMLResponse)
def lead_contacts(
    request: Request,
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return RedirectResponse(
        url=f"/leads/{lead.id}/edit#contacts",
        status_code=302,
    )


@app.post("/leads/{lead_id}/contacts/create")
def create_lead_contact(
    lead_id: int,
    contact_name: str = Form(...),
    title: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    linkedin_url: str | None = Form(None),
    address_street: str | None = Form(None),
    address_city: str | None = Form(None),
    address_state: str | None = Form(None),
    address_zipcode: str | None = Form(None),
    contact_type: ContactType = Form(ContactType.employee),
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    contact = LeadContact(
        lead_id=lead.id,
        contact_name=contact_name,
        title=title,
        email=email,
        phone=phone,
        linkedin_url=linkedin_url,
        address_street=address_street,
        address_city=address_city,
        address_state=address_state or "GA",
        address_zipcode=address_zipcode,
        contact_type=contact_type,
    )
    db.add(contact)
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit#contacts", status_code=303)


@app.post("/leads/{lead_id}/contacts/{contact_id}/delete")
def delete_lead_contact(
    lead_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")

    db.delete(contact)
    db.commit()
    return RedirectResponse(url=f"/leads/{lead_id}/edit#contacts", status_code=303)


@app.post("/leads/{lead_id}/contacts/{contact_id}/update")
def update_lead_contact(
    lead_id: int,
    contact_id: int,
    contact_name: str = Form(...),
    title: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    linkedin_url: str | None = Form(None),
    address_street: str | None = Form(None),
    address_city: str | None = Form(None),
    address_state: str | None = Form(None),
    address_zipcode: str | None = Form(None),
    contact_type: ContactType = Form(ContactType.employee),
    db: Session = Depends(get_db),
):
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact.contact_name = contact_name
    contact.title = title
    contact.email = email
    contact.phone = phone
    contact.linkedin_url = linkedin_url
    contact.address_street = address_street
    contact.address_city = address_city
    contact.address_state = address_state or "GA"
    contact.address_zipcode = address_zipcode
    contact.contact_type = contact_type
    contact.updated_at = datetime.utcnow()

    db.commit()
    return RedirectResponse(url=f"/leads/{lead_id}/edit#contacts", status_code=303)


@app.post("/leads/{lead_id}/contacts/{contact_id}/letters")
def generate_contact_letter(
    lead_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")

    address_fields = [
        contact.address_street,
        contact.address_city,
        contact.address_state,
        contact.address_zipcode,
    ]
    if not all(address_fields):
        raise HTTPException(
            status_code=400,
            detail="Contact must have street, city, state, and ZIP before generating a letter.",
        )

    property_details = get_property_for_lead(db, lead)
    if not property_details:
        property_details = _get_property_by_id(db, lead.property_id)

    if not property_details:
        raise HTTPException(
            status_code=400,
            detail="Lead is not associated with a property record.",
        )

    try:
        pdf_bytes, filename, saved_path = render_letter_pdf(
            templates.env, lead, contact, property_details
        )
    except LetterGenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    print_log = PrintLog(
        lead_id=lead.id,
        contact_id=contact.id,
        filename=filename,
        file_path=str(saved_path),
    )
    db.add(print_log)
    db.commit()

    return {
        "status": "ok",
        "filename": filename,
        "file_path": str(saved_path),
    }


@app.get("/leads/{lead_id}/print-logs")
def list_print_logs(
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    logs = _get_print_logs_for_lead(db, lead_id)
    return {"logs": [_serialize_print_log(log) for log in logs]}


@app.post("/leads/{lead_id}/print-logs/{log_id}/mark-mailed")
def mark_print_log_as_mailed(
    lead_id: int,
    log_id: int,
    db: Session = Depends(get_db),
):
    log = db.get(PrintLog, log_id)
    if not log or log.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Print log not found")

    if log.mailed:
        return _serialize_print_log(log)

    last_attempt = db.execute(
        select(LeadAttempt)
        .where(LeadAttempt.lead_id == lead_id)
        .order_by(LeadAttempt.attempt_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    next_attempt_number = (last_attempt.attempt_number + 1) if last_attempt else 1

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

    log.mailed = True
    log.mailed_at = datetime.utcnow()
    log.attempt_id = attempt.id
    db.commit()
    db.refresh(log)

    return _serialize_print_log(log)


@app.delete("/leads/{lead_id}/print-logs/{log_id}")
def delete_print_log(
    lead_id: int,
    log_id: int,
    db: Session = Depends(get_db),
):
    log = db.get(PrintLog, log_id)
    if not log or log.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Print log not found")

    if log.attempt_id:
        attempt = db.get(LeadAttempt, log.attempt_id)
        if attempt:
            db.delete(attempt)

    db.delete(log)
    db.commit()
    return {"status": "deleted"}


@app.get("/leads/{lead_id}/contacts/{contact_id}/prep-email")
def prep_email(
    lead_id: int,
    contact_id: int,
    profile: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Prepare email content for a contact."""
    try:
        email_data = prep_contact_email(db, lead_id, contact_id, profile_key=profile)
        return JSONResponse(content=email_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/leads/{lead_id}/contacts/{contact_id}/send-email")
def send_contact_email(
    lead_id: int,
    contact_id: int,
    subject: str = Form(...),
    body: str = Form(...),
    profile: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Send email to a contact and create attempt record."""
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    if not contact.email:
        raise HTTPException(status_code=400, detail="Contact has no email address")
    
    try:
        profile_config = resolve_profile(profile)
        # Send email
        send_email(
            to_email=contact.email,
            subject=subject,
            html_body=body,
            from_email=profile_config["from_email"],
            from_name=profile_config["from_name"],
            reply_to=profile_config["reply_to"],
        )
        
        # Get the next attempt number
        last_attempt = db.scalar(
            select(LeadAttempt)
            .where(LeadAttempt.lead_id == lead_id)
            .order_by(LeadAttempt.attempt_number.desc())
            .limit(1)
        )
        next_attempt_number = (last_attempt.attempt_number + 1) if last_attempt else 1
        
        # Create attempt record
        attempt = LeadAttempt(
            lead_id=lead.id,
            contact_id=contact.id,
            channel=ContactChannel.email,
            attempt_number=next_attempt_number,
            outcome="Email sent",
            notes=f"Subject: {subject[:100]}",
        )
        db.add(attempt)
        db.commit()
        
        return JSONResponse(content={"status": "success", "message": "Email sent successfully"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


@app.post("/leads/{lead_id}/contacts/{contact_id}/schedule-email")
def schedule_contact_email(
    lead_id: int,
    contact_id: int,
    subject: str = Form(...),
    body: str = Form(...),
    scheduled_at: str = Form(...),  # ISO format datetime string
    profile: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Schedule an email to be sent later."""
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    if not contact.email:
        raise HTTPException(status_code=400, detail="Contact has no email address")
    
    try:
        # Parse scheduled_at (expecting ISO format from frontend)
        scheduled_datetime = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        if scheduled_datetime.tzinfo is None:
            # Assume UTC if no timezone
            scheduled_datetime = scheduled_datetime.replace(tzinfo=timezone.utc)
        
        # Validate scheduled time is in the future
        if scheduled_datetime <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Scheduled time must be in the future")
        
        profile_config = resolve_profile(profile)
        body_with_marker = embed_profile_marker(body, profile_config["key"])
        
        # Create scheduled email record
        scheduled_email = ScheduledEmail(
            lead_id=lead.id,
            contact_id=contact.id,
            to_email=contact.email,
            subject=subject,
            body=body_with_marker,
            scheduled_at=scheduled_datetime,
            status=ScheduledEmailStatus.pending,
        )
        db.add(scheduled_email)
        db.commit()
        
        return JSONResponse(content={
            "status": "success",
            "message": "Email scheduled successfully",
            "scheduled_id": scheduled_email.id,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to schedule email: {str(e)}")


@app.get("/leads/{lead_id}/scheduled-emails")
def get_scheduled_emails(
    lead_id: int,
    db: Session = Depends(get_db),
):
    """Get all scheduled emails for a lead."""
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    scheduled_emails = db.query(ScheduledEmail).filter(
        ScheduledEmail.lead_id == lead_id
    ).order_by(ScheduledEmail.scheduled_at.desc()).all()
    
    result = []
    for email in scheduled_emails:
        contact_name = None
        contact_title = None
        if email.contact_id:
            contact = db.get(LeadContact, email.contact_id)
            if contact:
                contact_name = contact.contact_name
                contact_title = contact.title
        
        profile_key, clean_body = extract_profile_marker(email.body)
        
        result.append({
            "id": email.id,
            "contact_id": email.contact_id,
            "contact_name": contact_name,
            "contact_title": contact_title,
            "to_email": email.to_email,
            "subject": email.subject,
            "body": clean_body,
            "scheduled_at": email.scheduled_at.isoformat(),
            "status": email.status.value,
            "error_message": email.error_message,
            "created_at": email.created_at.isoformat(),
            "sent_at": email.sent_at.isoformat() if email.sent_at else None,
            "profile": profile_key,
        })
    
    return JSONResponse(content=result)


@app.get("/leads/{lead_id}/scheduled-emails/{scheduled_id}")
def get_scheduled_email(
    lead_id: int,
    scheduled_id: int,
    db: Session = Depends(get_db),
):
    """Get a single scheduled email for editing."""
    scheduled_email = db.get(ScheduledEmail, scheduled_id)
    if not scheduled_email or scheduled_email.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Scheduled email not found")
    
    contact_name = None
    contact_title = None
    if scheduled_email.contact_id:
        contact = db.get(LeadContact, scheduled_email.contact_id)
        if contact:
            contact_name = contact.contact_name
            contact_title = contact.title
    
    profile_key, clean_body = extract_profile_marker(scheduled_email.body)
    
    return JSONResponse(content={
        "id": scheduled_email.id,
        "contact_id": scheduled_email.contact_id,
        "contact_name": contact_name,
        "contact_title": contact_title,
        "to_email": scheduled_email.to_email,
        "subject": scheduled_email.subject,
        "body": clean_body,
        "scheduled_at": scheduled_email.scheduled_at.isoformat(),
        "status": scheduled_email.status.value,
        "error_message": scheduled_email.error_message,
        "created_at": scheduled_email.created_at.isoformat(),
        "sent_at": scheduled_email.sent_at.isoformat() if scheduled_email.sent_at else None,
        "profile": profile_key,
    })


@app.post("/leads/{lead_id}/scheduled-emails/{scheduled_id}/send-now")
def send_scheduled_email_now(
    lead_id: int,
    scheduled_id: int,
    db: Session = Depends(get_db),
):
    """Send a scheduled email immediately."""
    scheduled_email = db.get(ScheduledEmail, scheduled_id)
    if not scheduled_email or scheduled_email.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Scheduled email not found")
    
    if scheduled_email.status not in [ScheduledEmailStatus.pending, ScheduledEmailStatus.missed]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot send email with status: {scheduled_email.status.value}",
        )
    
    try:
        profile_key, clean_body = extract_profile_marker(scheduled_email.body)
        profile_config = resolve_profile(profile_key)
        
        # Send email
        send_email(
            to_email=scheduled_email.to_email,
            subject=scheduled_email.subject,
            html_body=clean_body,
            from_email=profile_config["from_email"],
            from_name=profile_config["from_name"],
            reply_to=profile_config["reply_to"],
        )
        
        # Mark as sent
        scheduled_email.status = ScheduledEmailStatus.sent
        scheduled_email.sent_at = datetime.now(timezone.utc)
        db.commit()
        
        # Create attempt record
        last_attempt = db.scalar(
            select(LeadAttempt)
            .where(LeadAttempt.lead_id == lead_id)
            .order_by(LeadAttempt.attempt_number.desc())
            .limit(1)
        )
        next_attempt_number = (last_attempt.attempt_number + 1) if last_attempt else 1
        
        attempt = LeadAttempt(
            lead_id=lead_id,
            contact_id=scheduled_email.contact_id,
            channel=ContactChannel.email,
            attempt_number=next_attempt_number,
            outcome="Email sent (scheduled, sent now)",
            notes=f"Originally scheduled for {scheduled_email.scheduled_at.isoformat()}. Subject: {scheduled_email.subject[:100]}",
        )
        db.add(attempt)
        db.commit()
        
        return JSONResponse(content={"status": "success", "message": "Email sent successfully"})
    except Exception as e:
        db.rollback()
        scheduled_email.status = ScheduledEmailStatus.failed
        scheduled_email.error_message = str(e)[:500]
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


@app.put("/leads/{lead_id}/scheduled-emails/{scheduled_id}")
def update_scheduled_email(
    lead_id: int,
    scheduled_id: int,
    subject: str = Form(None),
    body: str = Form(None),
    scheduled_at: str = Form(None),
    profile: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Update a scheduled email (subject, body, or scheduled time)."""
    scheduled_email = db.get(ScheduledEmail, scheduled_id)
    if not scheduled_email or scheduled_email.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Scheduled email not found")
    
    if scheduled_email.status not in [ScheduledEmailStatus.pending, ScheduledEmailStatus.missed, ScheduledEmailStatus.failed]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit email with status: {scheduled_email.status.value}",
        )
    
    try:
        target_profile_key = profile or extract_profile_marker(scheduled_email.body)[0]
        
        if subject is not None:
            scheduled_email.subject = subject
        if body is not None:
            scheduled_email.body = embed_profile_marker(body, target_profile_key)
        if scheduled_at is not None:
            scheduled_datetime = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            if scheduled_datetime.tzinfo is None:
                scheduled_datetime = scheduled_datetime.replace(tzinfo=timezone.utc)
            
            if scheduled_datetime <= datetime.now(timezone.utc):
                raise HTTPException(status_code=400, detail="Scheduled time must be in the future")
            
            scheduled_email.scheduled_at = scheduled_datetime
        
        # If profile changed but body not updated, ensure marker reflects new profile
        if profile is not None and body is None:
            _, current_body = extract_profile_marker(scheduled_email.body)
            scheduled_email.body = embed_profile_marker(current_body, target_profile_key)
        
        db.commit()
        return JSONResponse(content={"status": "success", "message": "Scheduled email updated"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update scheduled email: {str(e)}")


@app.delete("/leads/{lead_id}/scheduled-emails/{scheduled_id}")
def cancel_scheduled_email(
    lead_id: int,
    scheduled_id: int,
    db: Session = Depends(get_db),
):
    """Cancel a scheduled email."""
    scheduled_email = db.get(ScheduledEmail, scheduled_id)
    if not scheduled_email or scheduled_email.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Scheduled email not found")
    
    if scheduled_email.status != ScheduledEmailStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel email with status: {scheduled_email.status.value}",
        )
    
    scheduled_email.status = ScheduledEmailStatus.cancelled
    db.commit()
    
    return JSONResponse(content={"status": "success", "message": "Scheduled email cancelled"})

# ---------- ATTEMPTS / ACTIONS FOR A LEAD ----------

@app.get("/leads/{lead_id}/attempts", response_class=HTMLResponse)
def lead_attempts(
    request: Request,
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return RedirectResponse(
        url=f"/leads/{lead.id}/edit#attempts",
        status_code=302,
    )


@app.post("/leads/{lead_id}/attempts/create")
def create_lead_attempt(
    lead_id: int,
    channel: ContactChannel = Form(...),
    attempt_number: int = Form(1),
    contact_id: str | None = Form(None),
    outcome: str | None = Form(None),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Normalize contact_id from empty string
    if not contact_id:
        contact_id_val = None
    else:
        contact_id_val = int(contact_id)

    attempt = LeadAttempt(
        lead_id=lead.id,
        contact_id=contact_id_val,
        channel=channel,
        attempt_number=attempt_number,
        outcome=outcome,
        notes=notes,
    )
    db.add(attempt)
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit#attempts", status_code=303)


# ---------- COMMENTS FOR A LEAD ----------


@app.post("/leads/{lead_id}/comments/create")
def create_lead_comment(
    lead_id: int,
    body: str = Form(...),
    author: str | None = Form(None),
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    comment = LeadComment(
        lead_id=lead.id,
        body=body,
        author=author,
    )
    db.add(comment)
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit#comments", status_code=303)


@app.post("/leads/{lead_id}/comments/{comment_id}/delete")
def delete_lead_comment(
    lead_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
):
    comment = db.get(LeadComment, comment_id)
    if not comment or comment.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Comment not found")

    db.delete(comment)
    db.commit()
    return RedirectResponse(url=f"/leads/{lead_id}/edit#comments", status_code=303)

