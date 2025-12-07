# main.py
import os
from datetime import datetime, timezone, timedelta
from io import BytesIO
from decimal import Decimal, InvalidOperation
from typing import Any
from pathlib import Path
import json
import re
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, Request, Form, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, cast, String, update, case, and_, Table, MetaData, inspect, exists
from markupsafe import Markup, escape

from db import Base, SessionLocal, engine
from models import (
    PropertyView,
    OwnerRelationshipAuthority,
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
    _build_template_context,
    _render_template,
    _build_template_context,
    _render_template,
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
    # Pre-load LinkedIn templates from JSON at startup for instant access
    global _LINKEDIN_TEMPLATES_METADATA_CACHE, _LINKEDIN_TEMPLATES_CONTENT_CACHE
    if LINKEDIN_TEMPLATES_JSON.exists():
        _LINKEDIN_TEMPLATES_METADATA_CACHE, _LINKEDIN_TEMPLATES_CONTENT_CACHE = _preload_linkedin_templates()
        print(f"✓ Pre-loaded {len(_LINKEDIN_TEMPLATES_CONTENT_CACHE)} LinkedIn templates from JSON into memory")


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
DEFAULT_YEAR = "2025"

# Cache for discovered year tables
_YEAR_TABLES_LIST = None


def _get_available_years(db: Session) -> list[str]:
    """Discover available year tables from database."""
    global _YEAR_TABLES_LIST
    
    if _YEAR_TABLES_LIST is not None:
        return _YEAR_TABLES_LIST
    
    inspector = inspect(engine)
    all_tables = inspector.get_table_names()
    
    # Filter tables matching pattern ucp_main_year_e_YYYY
    year_tables = []
    for table_name in all_tables:
        if table_name.startswith("ucp_main_year_e_"):
            # Extract year from table name (e.g., "ucp_main_year_e_2025" -> "2025")
            year_match = re.search(r"ucp_main_year_e_(\d{4})$", table_name)
            if year_match:
                year = year_match.group(1)
                year_tables.append(year)
    
    # Sort descending (newest first)
    year_tables.sort(reverse=True)
    _YEAR_TABLES_LIST = year_tables
    return year_tables


def _get_property_table_for_year(year: str | None = None) -> Table:
    """Get SQLAlchemy Table object for the specified year's property table."""
    if not year:
        year = DEFAULT_YEAR
    
    table_name = f"ucp_main_year_e_{year}"
    
    # Check if table exists
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        raise HTTPException(
            status_code=404,
            detail=f"Property table for year {year} not found"
        )
    
    # Use reflection to get the table
    metadata = MetaData()
    return Table(
        table_name,
        metadata,
        autoload_with=engine,
        schema=None
    )


# Legacy constants for backward compatibility (will be replaced with dynamic table)
PROPERTY_AMOUNT_FILTER = PropertyView.propertyamount >= PROPERTY_MIN_AMOUNT
PROPERTY_ORDERING = (
    PropertyView.propertyamount.desc(),
    PropertyView.raw_hash.asc(),
)

APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "America/New_York"))

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


def _previous_monday_cutoff(now: datetime | None = None) -> datetime:
    """
    Return the most recent Monday at 6 PM (APP_TIMEZONE). If we're earlier than
    this week's Monday 6 PM, go back one more week. Result is returned in UTC.
    """
    now_local = (now or datetime.now(APP_TIMEZONE)).astimezone(APP_TIMEZONE)
    days_since_monday = now_local.weekday()
    monday_local = (now_local - timedelta(days=days_since_monday)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )
    if now_local < monday_local:
        monday_local -= timedelta(days=7)
    return monday_local.astimezone(timezone.utc)


def _is_lead_editable(lead: BusinessLead) -> bool:
    """
    Determine if a lead can be edited. Returns False for terminal/archived statuses.
    """
    read_only_statuses = {LeadStatus.competitor_claimed}
    return lead.status not in read_only_statuses


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


def _get_property_by_id(db: Session, property_id: str, year: str | None = None) -> dict | None:
    """Get property by ID from the specified year's table. Returns dict with property data."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = _get_property_table_for_year(year)
    
    result = db.execute(
        select(
            prop_table.c.row_hash.label("raw_hash"),  # Label as raw_hash for consistency
            prop_table.c.propertyid,
            prop_table.c.ownername,
            prop_table.c.propertyamount,
            prop_table.c.assigned_to_lead,
            prop_table.c.owneraddress1,
            prop_table.c.owneraddress2,
            prop_table.c.owneraddress3,
            prop_table.c.ownercity,
            prop_table.c.ownerstate,
            prop_table.c.ownerzipcode,
            prop_table.c.ownerrelation,
            prop_table.c.lastactivitydate,
            prop_table.c.reportyear,
            prop_table.c.holdername,
            prop_table.c.propertytypedescription,
        )
        .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
        .where(cast(prop_table.c.propertyid, String) == property_id)  # Cast to match text type
        .limit(1)
    ).first()
    
    if result:
        return dict(result._mapping)
    return None


def _get_property_by_order(db: Session, order_id: int, year: str | None = None) -> dict | None:
    """Get property by order ID from the specified year's table."""
    if not year:
        year = DEFAULT_YEAR
    
    raw_hash = _get_raw_hash_for_order(db, order_id, year)
    if not raw_hash:
        return None
    return _get_property_by_raw_hash(db, raw_hash, year)


def _get_property_by_raw_hash(db: Session, raw_hash: str, year: str | None = None) -> dict | None:
    """Get property by raw hash from the specified year's table. Returns dict with property data."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = _get_property_table_for_year(year)
    
    result = db.execute(
        select(
            prop_table.c.row_hash.label("raw_hash"),  # Label as raw_hash for consistency
            prop_table.c.propertyid,
            prop_table.c.ownername,
            prop_table.c.propertyamount,
            prop_table.c.assigned_to_lead,
            prop_table.c.owneraddress1,
            prop_table.c.owneraddress2,
            prop_table.c.owneraddress3,
            prop_table.c.ownercity,
            prop_table.c.ownerstate,
            prop_table.c.ownerzipcode,
            prop_table.c.ownerrelation,
            prop_table.c.lastactivitydate,
            prop_table.c.reportyear,
            prop_table.c.holdername,
            prop_table.c.propertytypedescription,
        )
        .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
        .where(prop_table.c.row_hash == raw_hash)  # Database column is "row_hash"
        .limit(1)
    ).first()
    
    if result:
        return dict(result._mapping)
    return None


def _get_property_details_for_lead(db: Session, lead: BusinessLead, year: str | None = None) -> dict | None:
    """Get property details for a lead, trying to find it in the specified year's table."""
    if not year:
        year = DEFAULT_YEAR
    
    # Try all available years if property not found in specified year
    available_years = _get_available_years(db)
    years_to_try = [year] + [y for y in available_years if y != year]
    
    for try_year in years_to_try:
        if lead.property_raw_hash:
            prop = _get_property_by_raw_hash(db, lead.property_raw_hash, try_year)
            if prop:
                return prop
        if lead.property_id:
            prop = _get_property_by_id(db, lead.property_id, try_year)
            if prop:
                return prop
    
    return None


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


def _build_lead_filters(
    q: str | None,
    attempt_type: str | None,
    attempt_operator: str | None,
    attempt_count_int: int | None,
    print_log_operator: str | None,
    print_log_count_int: int | None,
    print_log_mailed: str | None,
    scheduled_email_operator: str | None,
    scheduled_email_count_int: int | None,
    failed_email_operator: str | None,
    failed_email_count_int: int | None,
    status: str | None,
):
    """Build filter conditions for leads query. Returns list of filter conditions."""
    filters = []
    
    # Text search filter
    if q:
        pattern = f"%{q}%"
        filters.append(
            or_(
                BusinessLead.property_id.ilike(pattern),
                BusinessLead.owner_name.ilike(pattern)
            )
        )
    
    # Attempt count filter
    if attempt_type and attempt_operator and attempt_count_int is not None:
        attempt_filter = []
        if attempt_type != "all":
            attempt_filter.append(LeadAttempt.channel == ContactChannel[attempt_type])
        attempt_count_subq = (
            select(func.count(LeadAttempt.id))
            .where(LeadAttempt.lead_id == BusinessLead.id)
            .where(*attempt_filter)
            .correlate(BusinessLead)
            .scalar_subquery()
        )
        if attempt_operator == ">=":
            filters.append(attempt_count_subq >= attempt_count_int)
        elif attempt_operator == "=":
            filters.append(attempt_count_subq == attempt_count_int)
        elif attempt_operator == "<=":
            filters.append(attempt_count_subq <= attempt_count_int)

    # Print log count filter
    if print_log_operator and print_log_count_int is not None:
        print_log_filter = []
        if print_log_mailed == "mailed":
            print_log_filter.append(PrintLog.mailed == True)
        elif print_log_mailed == "not_mailed":
            print_log_filter.append(PrintLog.mailed == False)
        print_log_count_subq = (
            select(func.count(PrintLog.id))
            .where(PrintLog.lead_id == BusinessLead.id)
            .where(*print_log_filter)
            .correlate(BusinessLead)
            .scalar_subquery()
        )
        if print_log_operator == ">=":
            filters.append(print_log_count_subq >= print_log_count_int)
        elif print_log_operator == "=":
            filters.append(print_log_count_subq == print_log_count_int)
        elif print_log_operator == "<=":
            filters.append(print_log_count_subq <= print_log_count_int)

    # Scheduled email count filter (pending + sent)
    if scheduled_email_operator and scheduled_email_count_int is not None:
        scheduled_email_count_subq = (
            select(func.count(ScheduledEmail.id))
            .where(ScheduledEmail.lead_id == BusinessLead.id)
            .where(ScheduledEmail.status.in_([ScheduledEmailStatus.pending, ScheduledEmailStatus.sent]))
            .correlate(BusinessLead)
            .scalar_subquery()
        )
        if scheduled_email_operator == ">=":
            filters.append(scheduled_email_count_subq >= scheduled_email_count_int)
        elif scheduled_email_operator == "=":
            filters.append(scheduled_email_count_subq == scheduled_email_count_int)
        elif scheduled_email_operator == "<=":
            filters.append(scheduled_email_count_subq <= scheduled_email_count_int)

    # Failed email count filter
    if failed_email_operator and failed_email_count_int is not None:
        failed_email_count_subq = (
            select(func.count(ScheduledEmail.id))
            .where(ScheduledEmail.lead_id == BusinessLead.id)
            .where(ScheduledEmail.status == ScheduledEmailStatus.failed)
            .correlate(BusinessLead)
            .scalar_subquery()
        )
        if failed_email_operator == ">=":
            filters.append(failed_email_count_subq >= failed_email_count_int)
        elif failed_email_operator == "=":
            filters.append(failed_email_count_subq == failed_email_count_int)
        elif failed_email_operator == "<=":
            filters.append(failed_email_count_subq <= failed_email_count_int)

    # Status filter
    if status:
        try:
            status_enum = LeadStatus[status]
            filters.append(BusinessLead.status == status_enum)
        except (KeyError, ValueError):
            pass  # Invalid status, ignore
    
    return filters


def _build_filter_query_string(
    q: str | None,
    attempt_type: str | None,
    attempt_operator: str | None,
    attempt_count: str | None,
    print_log_operator: str | None,
    print_log_count: str | None,
    print_log_mailed: str | None,
    scheduled_email_operator: str | None,
    scheduled_email_count: str | None,
    failed_email_operator: str | None,
    failed_email_count: str | None,
    status: str | None,
) -> str:
    """Build query string from filter parameters."""
    from urllib.parse import urlencode
    params = {}
    if q:
        params["q"] = q
    if attempt_type and attempt_type != "all":
        params["attempt_type"] = attempt_type
    if attempt_operator:
        params["attempt_operator"] = attempt_operator
    if attempt_count:
        params["attempt_count"] = attempt_count
    if print_log_operator:
        params["print_log_operator"] = print_log_operator
    if print_log_count:
        params["print_log_count"] = print_log_count
    if print_log_mailed and print_log_mailed != "all":
        params["print_log_mailed"] = print_log_mailed
    if scheduled_email_operator:
        params["scheduled_email_operator"] = scheduled_email_operator
    if scheduled_email_count:
        params["scheduled_email_count"] = scheduled_email_count
    if failed_email_operator:
        params["failed_email_operator"] = failed_email_operator
    if failed_email_count:
        params["failed_email_count"] = failed_email_count
    if status:
        params["status"] = status
    if params:
        return "?" + urlencode(params)
    return ""


def _lead_navigation_info(
    db: Session,
    lead_id: int,
    q: str | None = None,
    attempt_type: str | None = None,
    attempt_operator: str | None = None,
    attempt_count_int: int | None = None,
    print_log_operator: str | None = None,
    print_log_count_int: int | None = None,
    print_log_mailed: str | None = None,
    scheduled_email_operator: str | None = None,
    scheduled_email_count_int: int | None = None,
    failed_email_operator: str | None = None,
    failed_email_count_int: int | None = None,
    status: str | None = None,
):
    """Get navigation info for a lead (prev/next based on filtered ordering)."""
    # Build filters using the same logic as list_leads
    filters = _build_lead_filters(
        q, attempt_type, attempt_operator, attempt_count_int,
        print_log_operator, print_log_count_int, print_log_mailed,
        scheduled_email_operator, scheduled_email_count_int,
        failed_email_operator, failed_email_count_int, status
    )
    
    # Use the same ordering as the leads list
    lead_ordering = BusinessLead.created_at.desc()
    
    # Create ranked subquery with prev/next, applying filters
    ranked_query = select(
        BusinessLead.id.label("lead_id"),
        func.row_number().over(order_by=lead_ordering).label("order_id"),
        func.lag(BusinessLead.id).over(order_by=lead_ordering).label("prev_lead_id"),
        func.lead(BusinessLead.id).over(order_by=lead_ordering).label("next_lead_id"),
    )
    
    if filters:
        ranked_query = ranked_query.where(and_(*filters))
    
    ranked = ranked_query.subquery()
    
    nav_row = db.execute(
        select(
            ranked.c.order_id,
            ranked.c.prev_lead_id,
            ranked.c.next_lead_id,
        ).where(ranked.c.lead_id == lead_id)
    ).one_or_none()
    
    if not nav_row:
        return {
            "order_id": None,
            "prev_lead_id": None,
            "next_lead_id": None,
        }
    
    return {
        "order_id": nav_row.order_id,
        "prev_lead_id": nav_row.prev_lead_id,
        "next_lead_id": nav_row.next_lead_id,
    }


def _property_navigation_info(db: Session, raw_hash: str, year: str | None = None):
    """Get property navigation info for the specified year's table."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = _get_property_table_for_year(year)
    property_ordering = (prop_table.c.propertyamount.desc(), prop_table.c.row_hash.asc())
    
    ranked = (
        select(
            prop_table.c.row_hash.label("raw_hash"),
            func.row_number().over(order_by=property_ordering).label("order_id"),
            func.lag(prop_table.c.row_hash).over(order_by=property_ordering).label("prev_hash"),
            func.lead(prop_table.c.row_hash).over(order_by=property_ordering).label("next_hash"),
        )
        .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
        .subquery()
    )
    nav_row = db.execute(
        select(
            ranked.c.order_id,
            ranked.c.prev_hash,
            ranked.c.next_hash,
        ).where(ranked.c.raw_hash == raw_hash)
    ).one_or_none()
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


def _get_raw_hash_for_order(db: Session, order_id: int, year: str | None = None) -> str | None:
    """Get raw hash for a property by order ID from the specified year's table."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = _get_property_table_for_year(year)
    property_ordering = (prop_table.c.propertyamount.desc(), prop_table.c.row_hash.asc())
    
    ranked = (
        select(
            prop_table.c.row_hash.label("raw_hash"),  # Database column is "row_hash", label as "raw_hash"
            func.row_number().over(order_by=property_ordering).label("order_id"),
        )
        .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
        .subquery()
    )
    return db.scalar(
        select(ranked.c.raw_hash).where(ranked.c.order_id == order_id)
    )


def _build_gpt_payload(lead: BusinessLead, prop: dict) -> dict[str, Any]:
    """Build GPT payload from lead and property dict."""
    report_year_value = None
    if prop.get("reportyear"):
        try:
            report_year_value = int(str(prop.get("reportyear")))
        except (TypeError, ValueError):
            report_year_value = None

    return {
        "business_name": lead.owner_name or prop.get("ownername") or "",
        "property_state": prop.get("ownerstate") or "",
        "holder_name_on_record": prop.get("holdername") or "",
        "last_activity_date": prop.get("lastactivitydate") or "",
        "property_report_year": report_year_value,
    }

@app.get("/", response_class=HTMLResponse)
@app.get("/properties", response_class=HTMLResponse)
def list_properties(
    request: Request,
    page: int = 1,
    q: str | None = None,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    claim_authority: str | None = Query(None, description="Claim Authority: Unknown, Single, Joint"),
    db: Session = Depends(get_db),
):
    if page < 1:
        page = 1

    # Default to current year if not specified
    if not year:
        year = DEFAULT_YEAR
    
    # Validate year exists
    available_years = _get_available_years(db)
    if year not in available_years:
        year = DEFAULT_YEAR
    
    # Get dynamic table for the selected year
    prop_table = _get_property_table_for_year(year)
    
    # Build filters using dynamic table
    filters = [prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT]
    
    cutoff = _previous_monday_cutoff()
    if prop_table.c.last_seen is not None:
        filters.append(prop_table.c.last_seen >= cutoff)

    if q:
        pattern = f"%{q}%"
        prop_id_text = cast(prop_table.c.propertyid, String)
        filters.append(
            or_(
                prop_id_text.ilike(pattern),
                prop_table.c.ownername.ilike(pattern),
            )
        )

    # Join with owner_relationship_authority and filter by Claim_Authority if specified
    # Join condition: owner_relationship_authority.Code = PropertyView.ownerrelation
    # Default to "Single" only if no claim_authority parameter is provided at all
    # If claim_authority is empty string (from "All" selection), don't apply filter
    claim_authority_filter = None
    if claim_authority is None:
        # No parameter provided - default to "Single"
        claim_authority_filter = "Single"
        claim_authority_display = "Single"
    elif claim_authority.strip() == "":
        # "All" was selected - don't apply claim_authority filter
        claim_authority_filter = None
        claim_authority_display = ""
    else:
        # Specific value selected
        claim_authority_filter = claim_authority
        claim_authority_display = claim_authority
    
    # Handle potential whitespace and case issues
    join_condition = None
    if claim_authority_filter and claim_authority_filter.lower() in ("unknown", "single", "joint"):
        # Join condition: trim both sides to handle whitespace (varchar(50) and text are compatible)
        join_condition = func.trim(OwnerRelationshipAuthority.code) == func.trim(prop_table.c.ownerrelation)
        
        # Add filter for Claim_Authority - trim and compare case-insensitively
        # Normalize the input to match database values (Unknown, Single, Joint)
        filters.append(
            func.upper(func.trim(OwnerRelationshipAuthority.Claim_Authority)) == claim_authority_filter.upper()
        )

    # Build ordering for dynamic table
    # Note: database column is "row_hash", not "raw_hash"
    property_ordering = (prop_table.c.propertyamount.desc(), prop_table.c.row_hash.asc())

    # Build base query with join if filtering by Claim_Authority
    if join_condition is not None:
        count_stmt = (
            select(func.count())
            .select_from(prop_table)
            .join(OwnerRelationshipAuthority, join_condition)
            .where(*filters)
        )

        ranked_stmt = (
            select(
                prop_table.c.row_hash.label("raw_hash"),  # Database column is "row_hash", label as "raw_hash"
                prop_table.c.propertyid.label("propertyid"),
                prop_table.c.ownername.label("ownername"),
                prop_table.c.propertyamount.label("propertyamount"),
                prop_table.c.assigned_to_lead.label("assigned_to_lead"),
                func.row_number().over(order_by=property_ordering).label("order_id"),
            )
            .join(OwnerRelationshipAuthority, join_condition)
            .where(*filters)
        )
    else:
        count_stmt = (
            select(func.count())
            .select_from(prop_table)
            .where(*filters)
        )

        ranked_stmt = (
            select(
                prop_table.c.row_hash.label("raw_hash"),  # Database column is "row_hash", label as "raw_hash"
                prop_table.c.propertyid.label("propertyid"),
                prop_table.c.ownername.label("ownername"),
                prop_table.c.propertyamount.label("propertyamount"),
                prop_table.c.assigned_to_lead.label("assigned_to_lead"),
                func.row_number().over(order_by=property_ordering).label("order_id"),
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
            "year": year,
            "available_years": available_years,
            "claim_authority": claim_authority_display,
        },
    )


@app.get(
    "/properties/{property_id}",
    response_class=HTMLResponse,
)
def property_detail(
    request: Request,
    property_id: str,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    if not year:
        year = DEFAULT_YEAR
    
    prop = _get_property_by_id(db, property_id, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop["raw_hash"], year)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.get("assigned_to_lead")

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
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    # 1) Ensure we actually got a non-empty property_id
    if not property_id:
        raise HTTPException(status_code=400, detail="property_id query parameter is required")

    # Default to current year if not specified
    if not year:
        year = DEFAULT_YEAR

    # 2) Fetch row from the view using propertyid as PK
    prop = _get_property_by_id(db, property_id, year)
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

    # 3) Pass the 3 fields to the template
    phone_script_context = _build_phone_script_context(
        prop.get("ownername") if prop else None,
        prop.get("propertyid") if prop else None,
        prop.get("propertyamount") if prop else None,
        prop,  # Pass dict instead of PropertyView object
    )

    return templates.TemplateResponse(
        "lead_form.html",
        {
            "request": request,
            "lead": None,
            "mode": "create",
            "property_id": prop["propertyid"],          # view column
            "owner_name": prop["ownername"],           # view column
            "property_amount": prop["propertyamount"], # view column
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


@app.get("/api/properties/{property_id}")
def property_detail_json(
    property_id: str,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    # Default to current year if not specified
    if not year:
        year = DEFAULT_YEAR
    
    prop = _get_property_by_id(db, property_id, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop["raw_hash"], year)

    return JSONResponse(
        {
            "property": prop,
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
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    # Default to current year if not specified
    if not year:
        year = DEFAULT_YEAR
    
    prop = _get_property_by_raw_hash(db, raw_hash, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop["raw_hash"], year)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.get("assigned_to_lead")

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
    # Default to current year if not specified
    if not year:
        year = DEFAULT_YEAR
    
    prop = _get_property_by_order(db, order_id, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop["raw_hash"], year)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.get("assigned_to_lead")

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
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    # Default to current year if not specified
    if not year:
        year = DEFAULT_YEAR
    
    prop = _get_property_by_order(db, order_id, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop["raw_hash"], year)

    return JSONResponse(
        {
            "property": prop,
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
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    # Attempt filters
    attempt_type: str | None = Query(None, description="Type: all, email, phone, mail"),
    attempt_operator: str | None = Query(None, description="Operator: >=, =, <="),
    attempt_count: str | None = Query(None, description="Count number"),
    # Print log filters
    print_log_operator: str | None = Query(None, description="Operator: >=, =, <="),
    print_log_count: str | None = Query(None, description="Count number"),
    print_log_mailed: str | None = Query(None, description="Mailed status: all, mailed, not_mailed"),
    # Scheduled email filters
    scheduled_email_operator: str | None = Query(None, description="Operator: >=, =, <="),
    scheduled_email_count: str | None = Query(None, description="Count number"),
    # Failed email filters
    failed_email_operator: str | None = Query(None, description="Operator: >=, =, <="),
    failed_email_count: str | None = Query(None, description="Count number"),
    # Status filter
    status: str | None = Query(None, description="Lead status"),
    db: Session = Depends(get_db),
):
    # Convert string count parameters to integers, handling empty strings
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
    if page < 1:
        page = 1

    # Base query
    stmt = select(BusinessLead)
    count_stmt = select(func.count()).select_from(BusinessLead)

    # Filter leads by year: only show leads whose properties exist in the selected year's table
    prop_table = _get_property_table_for_year(year)
    year_filter = or_(
        # Check if property_raw_hash exists in the year's table
        and_(
            BusinessLead.property_raw_hash.is_not(None),
            exists(
                select(1)
                .select_from(prop_table)
                .where(prop_table.c.row_hash == BusinessLead.property_raw_hash)  # Database column is "row_hash"
                .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
            )
        ),
        # Or check if property_id exists in the year's table
        # Cast propertyid to text to match BusinessLead.property_id type
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

    # Build filters using helper function
    filters = _build_lead_filters(
        q, attempt_type, attempt_operator, attempt_count_int,
        print_log_operator, print_log_count_int, print_log_mailed,
        scheduled_email_operator, scheduled_email_count_int,
        failed_email_operator, failed_email_count_int, status
    )
    
    # Add year filter to filters list
    filters.append(year_filter)

    # Apply all filters
    if filters:
        stmt = stmt.where(and_(*filters))
        count_stmt = count_stmt.where(and_(*filters))

    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(BusinessLead.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    leads = db.scalars(stmt).all()

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1

    # Add editable flag to each lead for template rendering
    leads_with_flags = [(lead, _is_lead_editable(lead)) for lead in leads]

    return templates.TemplateResponse(
        "leads.html",
        {
            "request": request,
            "leads_with_flags": leads_with_flags,
            "page": page,
            "total_pages": total_pages,
            "q": q or "",
            "total": total,
            # Filter values for template
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
            "available_years": _get_available_years(db),
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

    # Try to find property in any available year
    prop = _get_property_details_for_lead(db, lead)

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


@app.get("/leads/{lead_id}/view", response_class=HTMLResponse)
def view_lead(
    request: Request,
    lead_id: int,
    # Filter parameters (same as list_leads)
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
    
    # Parse count parameters
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
    
    # Get navigation info with filters
    nav = _lead_navigation_info(
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

    property_details = _get_property_details_for_lead(db, lead)
    phone_script_context = _build_phone_script_context(
        lead.owner_name,
        lead.property_id,
        lead.property_amount,
        property_details,
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
            "can_generate_letters": False,  # Disable in view mode
            "phone_scripts": PHONE_SCRIPTS,
            "phone_scripts_json": PHONE_SCRIPTS_JSON,
            "phone_script_context_json": json.dumps(phone_script_context, default=str),
            "print_logs_json": print_logs_json,
            # Navigation info
            "prev_lead_id": nav["prev_lead_id"],
            "next_lead_id": nav["next_lead_id"],
            # Filter params for navigation links
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


@app.get("/leads/{lead_id}/edit", response_class=HTMLResponse)
def edit_lead(
    request: Request,
    lead_id: int,
    edit_contact_id: int | None = None,
    # Filter parameters (same as list_leads)
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
    
    # Prevent editing of read-only leads
    if not _is_lead_editable(lead):
        # Preserve filter params in redirect
        filter_query = _build_filter_query_string(
            q, attempt_type, attempt_operator, attempt_count,
            print_log_operator, print_log_count, print_log_mailed,
            scheduled_email_operator, scheduled_email_count,
            failed_email_operator, failed_email_count, status
        )
        return RedirectResponse(url=f"/leads/{lead_id}/view{filter_query}", status_code=303)
    
    # Parse count parameters
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
    
    # Get navigation info with filters
    nav = _lead_navigation_info(
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
            "linkedin_outcomes": LINKEDIN_OUTCOMES,
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
            # Navigation info
            "prev_lead_id": nav["prev_lead_id"],
            "next_lead_id": nav["next_lead_id"],
            # Filter params for navigation links
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
        pdf_bytes, filename = render_letter_pdf(
            templates.env, lead, contact, property_details
        )
    except LetterGenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    display_path = f"Downloads/{filename}"
    print_log = PrintLog(
        lead_id=lead.id,
        contact_id=contact.id,
        filename=filename,
        file_path=display_path,
    )
    db.add(print_log)
    db.commit()

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)


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
    template_variant: str = Query("initial", description="Template variant: initial, followup_1, followup_2"),
    db: Session = Depends(get_db),
):
    """Prepare email content for a contact."""
    # Validate template_variant
    if template_variant not in ("initial", "followup_1", "followup_2"):
        raise HTTPException(status_code=400, detail="Invalid template_variant. Must be one of: initial, followup_1, followup_2")
    
    try:
        email_data = prep_contact_email(db, lead_id, contact_id, profile_key=profile, template_variant=template_variant)
        return JSONResponse(content=email_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# LinkedIn Templates
LINKEDIN_TEMPLATE_DIR = Path(__file__).parent / "templates" / "linkedin"
LINKEDIN_TEMPLATES_JSON = LINKEDIN_TEMPLATE_DIR / "templates.json"

# Predefined LinkedIn attempt outcomes
LINKEDIN_OUTCOMES = [
    "Connection Request Sent",
    "Connection Accepted",
    "LinkedIn Message 1 Sent",
    "LinkedIn Message 2 Sent",
    "LinkedIn Message 3 Sent",
    "InMail Sent",
    "No Response",
    "Connection Declined",
    "Other",
]


def _load_linkedin_templates_from_json() -> tuple[dict, dict]:
    """
    Load LinkedIn templates from JSON file.
    Returns (metadata_dict, content_dict) where:
    - metadata_dict: structured like the old discovery format for compatibility
    - content_dict: template_name -> content mapping
    """
    # Initialize with proper structure even if JSON doesn't exist
    metadata = {
        "connection_requests": [],
        "accepted_messages": [],
        "inmail": []
    }
    content_cache = {}
    
    if not LINKEDIN_TEMPLATES_JSON.exists():
        return metadata, content_cache
    
    with open(LINKEDIN_TEMPLATES_JSON, "r", encoding="utf-8") as f:
        json_data = json.load(f)
    
    # Process connection_requests
    if "connection_requests" in json_data:
        cr_data = json_data["connection_requests"]
        # Agent
        if "agent" in cr_data:
            template = cr_data["agent"].copy()
            template["name"] = "agent_connection_request.txt"
            metadata["connection_requests"].append(template)
            content_cache["agent_connection_request.txt"] = template["content"]
        
        # Leader
        if "leader" in cr_data:
            for status in ["active", "dissolved", "acquired"]:
                if status in cr_data["leader"]:
                    template = cr_data["leader"][status].copy()
                    template["name"] = f"leader_{status}_connection_request.txt"
                    metadata["connection_requests"].append(template)
                    content_cache[template["name"]] = template["content"]
    
    # Process accepted_messages
    if "accepted_messages" in json_data:
        am_data = json_data["accepted_messages"]
        for contact_type in ["leader", "agent"]:
            if contact_type in am_data:
                for status in ["active", "dissolved", "acquired"]:
                    if status in am_data[contact_type]:
                        for msg_num in ["1", "2", "3"]:
                            if msg_num in am_data[contact_type][status]:
                                template = am_data[contact_type][status][msg_num].copy()
                                template["name"] = f"{contact_type}_{status}_message_{msg_num}.txt"
                                metadata["accepted_messages"].append(template)
                                content_cache[template["name"]] = template["content"]
    
    # Process inmail
    if "inmail" in json_data:
        inmail_data = json_data["inmail"]
        if "leader" in inmail_data:
            for status in ["active", "dissolved", "acquired"]:
                if status in inmail_data["leader"]:
                    template = inmail_data["leader"][status].copy()
                    template["name"] = f"leader_{status}_inmail.txt"
                    metadata["inmail"].append(template)
                    content_cache[template["name"]] = template["content"]
    
    # Sort for consistent ordering (same as before)
    metadata["connection_requests"].sort(key=lambda x: (
        0 if x["contact_type"] == "agent" else 1,
        x.get("business_status") or ""
    ))
    metadata["accepted_messages"].sort(key=lambda x: (
        x["contact_type"],
        x.get("business_status") or "",
        int(x["attempt"].split("_")[1]) if x["attempt"] and "_" in x["attempt"] else 0
    ))
    metadata["inmail"].sort(key=lambda x: x.get("business_status") or "")
    
    return metadata, content_cache


def _discover_linkedin_templates() -> dict:
    """
    Load LinkedIn templates from JSON file.
    Returns structured template metadata organized by category.
    """
    metadata, _ = _load_linkedin_templates_from_json()
    return metadata


# Cache templates metadata and content to avoid file I/O on every request
_LINKEDIN_TEMPLATES_METADATA_CACHE = None
_LINKEDIN_TEMPLATES_CONTENT_CACHE = None


def _preload_linkedin_templates() -> tuple[dict, dict]:
    """
    Pre-load all LinkedIn templates (metadata + content) from JSON at startup.
    Returns (metadata_dict, content_dict).
    """
    return _load_linkedin_templates_from_json()


def _get_linkedin_templates_metadata() -> dict:
    """Get LinkedIn templates metadata (cached, loaded at startup)."""
    global _LINKEDIN_TEMPLATES_METADATA_CACHE, _LINKEDIN_TEMPLATES_CONTENT_CACHE
    if _LINKEDIN_TEMPLATES_METADATA_CACHE is None:
        _LINKEDIN_TEMPLATES_METADATA_CACHE, _LINKEDIN_TEMPLATES_CONTENT_CACHE = _preload_linkedin_templates()
    return _LINKEDIN_TEMPLATES_METADATA_CACHE


def _get_linkedin_template_content(template_name: str) -> str:
    """Get LinkedIn template content from cache (no file I/O)."""
    global _LINKEDIN_TEMPLATES_METADATA_CACHE, _LINKEDIN_TEMPLATES_CONTENT_CACHE
    if _LINKEDIN_TEMPLATES_CONTENT_CACHE is None:
        _LINKEDIN_TEMPLATES_METADATA_CACHE, _LINKEDIN_TEMPLATES_CONTENT_CACHE = _preload_linkedin_templates()
    return _LINKEDIN_TEMPLATES_CONTENT_CACHE.get(template_name, "")


def _get_linkedin_connection_status(db: Session, contact_id: int) -> dict:
    """
    Determine LinkedIn connection status and message progression for a contact.
    
    Returns:
    {
        "is_connected": bool,
        "has_connection_request": bool,
        "inmail_sent": bool,
        "last_message_number": int | None,  # 1, 2, or 3
        "can_send_connection": bool,
        "can_send_messages": bool,
        "can_send_inmail": bool,
        "next_message_number": int | None,  # Which message to show next (1, 2, or 3)
        "all_followups_complete": bool
    }
    """
    # Get all LinkedIn attempts for this contact
    linkedin_attempts = db.query(LeadAttempt).filter(
        LeadAttempt.contact_id == contact_id,
        LeadAttempt.channel == ContactChannel.linkedin
    ).order_by(LeadAttempt.created_at.desc()).all()
    
    is_connected = False
    has_connection_request = False
    inmail_sent = False
    last_message_number = None
    
    for attempt in linkedin_attempts:
        outcome = (attempt.outcome or "").strip()
        
        # Check for connection status
        if "Connection Accepted" in outcome:
            is_connected = True
        elif "Connection Request Sent" in outcome:
            has_connection_request = True
        
        # Check for InMail sent
        if "InMail Sent" in outcome or "inmail" in outcome.lower():
            inmail_sent = True
        
        # Check for message numbers
        if "Message 1" in outcome or "Follow-up 1" in outcome:
            if last_message_number is None:
                last_message_number = 1
        elif "Message 2" in outcome or "Follow-up 2" in outcome:
            if last_message_number is None or last_message_number < 2:
                last_message_number = 2
        elif "Message 3" in outcome or "Follow-up 3" in outcome:
            if last_message_number is None or last_message_number < 3:
                last_message_number = 3
    
    # Determine what can be sent
    can_send_connection = not has_connection_request and not is_connected
    can_send_messages = is_connected
    can_send_inmail = has_connection_request and not is_connected and not inmail_sent
    
    # Determine next message number and completion status
    all_followups_complete = False
    if is_connected:
        if last_message_number is None:
            next_message_number = 1
        elif last_message_number < 3:
            next_message_number = last_message_number + 1
        else:
            next_message_number = None  # All messages sent
            all_followups_complete = True
    else:
        next_message_number = None
    
    return {
        "is_connected": is_connected,
        "has_connection_request": has_connection_request,
        "inmail_sent": inmail_sent,
        "last_message_number": last_message_number,
        "can_send_connection": can_send_connection,
        "can_send_messages": can_send_messages,
        "can_send_inmail": can_send_inmail,
        "next_message_number": next_message_number,
        "all_followups_complete": all_followups_complete
    }


@app.get("/leads/{lead_id}/linkedin-templates")
def get_linkedin_templates(
    lead_id: int,
    contact_id: int = Query(None, description="Contact ID to filter templates by contact type"),
    db: Session = Depends(get_db),
):
    """Get list of available LinkedIn templates, filtered by contact type and connection status."""
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # If contact_id is provided, filter templates based on contact type and connection status
    if contact_id:
        contact = db.get(LeadContact, contact_id)
        if not contact or contact.lead_id != lead_id:
            raise HTTPException(status_code=404, detail="Contact not found")
        
        # Get LinkedIn connection status
        connection_status = _get_linkedin_connection_status(db, contact_id)
        
        # Filter templates based on contact type and business status
        filtered_templates = {}
        
        # Determine business status
        business_status = None
        if lead.business_owner_status == BusinessOwnerStatus.dissolved:
            business_status = "dissolved"
        elif lead.business_owner_status in (BusinessOwnerStatus.acquired_or_merged, BusinessOwnerStatus.active_renamed):
            business_status = "acquired"
        elif lead.business_owner_status == BusinessOwnerStatus.active:
            business_status = "active"
        # Default to active if status is None or unknown
        if business_status is None:
            business_status = "active"
        
        # Get templates (use cached discovery)
        templates = _get_linkedin_templates_metadata()
        
        # Connection requests: only show if connection request hasn't been sent
        if connection_status["can_send_connection"]:
            if contact.contact_type == ContactType.agent:
                filtered_templates["connection_requests"] = [
                    t for t in templates["connection_requests"]
                    if t.get("contact_type") == "agent"
                ]
            else:
                filtered_templates["connection_requests"] = [
                    t for t in templates["connection_requests"]
                    if t.get("contact_type") == "leader" and (
                        t.get("business_status") == business_status or 
                        t.get("business_status") is None
                    )
                ]
        else:
            filtered_templates["connection_requests"] = []
        
        # Accepted messages: only show if connected, and filter to show only next message
        if connection_status["can_send_messages"]:
            all_messages = []
            if contact.contact_type == ContactType.agent:
                all_messages = [
                    t for t in templates["accepted_messages"]
                    if t.get("contact_type") == "agent" and (
                        t.get("business_status") == business_status or
                        t.get("business_status") is None
                    )
                ]
            else:
                all_messages = [
                    t for t in templates["accepted_messages"]
                    if t.get("contact_type") == "leader" and (
                        t.get("business_status") == business_status or
                        t.get("business_status") is None
                    )
                ]
            
            # Filter to show only the next message based on progression
            if connection_status["next_message_number"]:
                filtered_templates["accepted_messages"] = [
                    t for t in all_messages
                    if t.get("attempt") == f"followup_{connection_status['next_message_number']}"
                ]
            else:
                # All messages sent
                filtered_templates["accepted_messages"] = []
        else:
            filtered_templates["accepted_messages"] = []
        
        # InMail templates: only show if connection request sent but not accepted, and InMail not already sent
        if connection_status["can_send_inmail"] and not connection_status.get("inmail_sent", False):
            if contact.contact_type != ContactType.agent:
                # Filter InMail templates by business status, but always return at least one
                inmail_templates = []
                all_inmail = templates.get("inmail", [])
                
                # Try to find exact match first
                for t in all_inmail:
                    if t.get("business_status") == business_status:
                        inmail_templates.append(t)
                        break
                
                # If no exact match, use active template as fallback
                if not inmail_templates:
                    for t in all_inmail:
                        if t.get("business_status") == "active":
                            inmail_templates.append(t)
                            break
                
                # Final fallback: return first available template (should always have at least one)
                if not inmail_templates and all_inmail:
                    inmail_templates = [all_inmail[0]]
                
                filtered_templates["inmail"] = inmail_templates
            else:
                filtered_templates["inmail"] = []
        else:
            filtered_templates["inmail"] = []
        
        return JSONResponse(content={
            "templates": filtered_templates,
            "connection_status": connection_status
        })
    
    # If no contact_id, return all templates
    return JSONResponse(content={"templates": _get_linkedin_templates_metadata()})


@app.get("/leads/{lead_id}/contacts/{contact_id}/linkedin-preview")
def preview_linkedin_template(
    lead_id: int,
    contact_id: int,
    template_name: str = Query(..., description="Template filename"),
    profile: str = Query(None, description="Profile key"),
    db: Session = Depends(get_db),
):
    """Preview LinkedIn template with placeholders filled."""
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # Get property details
    prop = _get_property_details_for_lead(db, lead)
    
    # Resolve profile
    profile_data = resolve_profile(profile)
    
    # Build context with profile for LinkedIn placeholders
    context = _build_template_context(lead, contact, prop, profile=profile_data)
    
    # Get template content from cache (no file I/O)
    content = _get_linkedin_template_content(template_name)
    if not content:
        raise HTTPException(status_code=404, detail=f"Template {template_name} not found")
    
    # Extract subject line for InMail templates (first line if it starts with "Subject:")
    subject = None
    body = content
    if content.startswith("Subject:"):
        lines = content.split("\n", 1)
        # Extract subject from first line (handles both with and without newline)
        subject_line = lines[0].replace("Subject:", "").strip()
        # Body is the rest (if newline exists) or empty string (if no newline)
        body = lines[1].strip() if len(lines) == 2 else ""
        # Replace placeholders in subject
        for key, value in context.items():
            placeholder = f"[{key}]"
            subject_line = subject_line.replace(placeholder, str(value) if value else "")
        subject = subject_line
    
    # Replace placeholders in body
    for key, value in context.items():
        placeholder = f"[{key}]"
        body = body.replace(placeholder, str(value) if value else "")
    
    response_data = {"preview": body}
    if subject:
        response_data["subject"] = subject
        response_data["has_subject"] = True
    
    return JSONResponse(content=response_data)


@app.post("/leads/{lead_id}/contacts/{contact_id}/linkedin-mark-sent")
def mark_linkedin_message_sent(
    lead_id: int,
    contact_id: int,
    template_name: str = Form(..., description="Template filename"),
    template_category: str = Form(..., description="Template category: connection_requests, accepted_messages, or inmail"),
    db: Session = Depends(get_db),
):
    """Mark a LinkedIn message as sent and create an attempt record."""
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # Determine outcome based on template category and name
    outcome = None
    if template_category == "connection_requests":
        outcome = "Connection Request Sent"
    elif template_category == "accepted_messages":
        # Determine message number from template name
        if "message_1" in template_name or "followup_1" in template_name:
            outcome = "LinkedIn Message 1 Sent"
        elif "message_2" in template_name or "followup_2" in template_name:
            outcome = "LinkedIn Message 2 Sent"
        elif "message_3" in template_name or "followup_3" in template_name:
            outcome = "LinkedIn Message 3 Sent"
        else:
            outcome = "LinkedIn Message Sent"
    elif template_category == "inmail":
        outcome = "InMail Sent"
    else:
        outcome = "LinkedIn Message Sent"
    
    # Get the next attempt number for this lead
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
        channel=ContactChannel.linkedin,
        attempt_number=next_attempt_number,
        outcome=outcome,
        notes=f"Template: {template_name}",
    )
    db.add(attempt)
    db.commit()
    
    return JSONResponse(content={
        "status": "success",
        "message": "LinkedIn message marked as sent",
        "attempt_id": attempt.id
    })


@app.post("/leads/{lead_id}/contacts/{contact_id}/linkedin-connection-accepted")
def mark_linkedin_connection_accepted(
    lead_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    """Mark LinkedIn connection as accepted and create an attempt record."""
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # Get the next attempt number for this lead
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
        channel=ContactChannel.linkedin,
        attempt_number=next_attempt_number,
        outcome="Connection Accepted",
        notes="LinkedIn connection request was accepted",
    )
    db.add(attempt)
    db.commit()
    
    return JSONResponse(content={
        "status": "success",
        "message": "LinkedIn connection marked as accepted",
        "attempt_id": attempt.id
    })


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
        # Send email with profile-specific SMTP credentials
        send_email(
            to_email=contact.email,
            subject=subject,
            html_body=body,
            from_email=profile_config["from_email"],
            from_name=profile_config["from_name"],
            reply_to=profile_config["reply_to"],
            smtp_username=profile_config["from_email"],  # Use profile email as SMTP username
            smtp_password=profile_config.get("smtp_password") or None,  # Use profile password
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
        
        # Send email with profile-specific SMTP credentials
        send_email(
            to_email=scheduled_email.to_email,
            subject=scheduled_email.subject,
            html_body=clean_body,
            from_email=profile_config["from_email"],
            from_name=profile_config["from_name"],
            reply_to=profile_config["reply_to"],
            smtp_username=profile_config["from_email"],  # Use profile email as SMTP username
            smtp_password=profile_config.get("smtp_password") or None,  # Use profile password
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

    # Auto-calculate next attempt number (same logic as programmatic attempts)
    last_attempt = db.scalar(
        select(LeadAttempt)
        .where(LeadAttempt.lead_id == lead_id)
        .order_by(LeadAttempt.attempt_number.desc())
        .limit(1)
    )
    next_attempt_number = (last_attempt.attempt_number + 1) if last_attempt else 1

    attempt = LeadAttempt(
        lead_id=lead.id,
        contact_id=contact_id_val,
        channel=channel,
        attempt_number=next_attempt_number,
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

