# main.py
import os
from datetime import datetime, timezone, timedelta
from io import BytesIO
from decimal import Decimal, InvalidOperation
from typing import Any, List, Callable, Optional
from dataclasses import dataclass
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

from db import Base, SessionLocal, engine, get_db
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
    LeadJourney,
    JourneyMilestone,
    JourneyStatus,
    JourneyMilestoneType,
    MilestoneStatus,
)

from services.letter_service import (
    LetterGenerationError,
    get_property_for_lead,
    render_letter_pdf,
)
from services.gpt_service import fetch_entity_intelligence, GPTConfigError, GPTServiceError
from services.email_service import (
    prep_contact_email,
    send_email,
    resolve_profile,
    embed_profile_marker,
    _build_template_context,
    _render_template,
    extract_profile_marker,
    PROFILE_REGISTRY,
)
from services.email_scheduler import start_scheduler, stop_scheduler

from fastapi.templating import Jinja2Templates

# Import routers
from routers import properties as properties_router
from routers import leads as leads_router
from routers import contacts as contacts_router
from routers import linkedin as linkedin_router
from routers import emails as emails_router
from routers import attempts as attempts_router
from routers import journey_api as journey_api_router

# Import router modules directly for template sharing
import routers.leads
import routers.contacts
import routers.properties

# Import utilities
from utils import (
    format_currency,
    get_lead_or_404,
    get_contact_or_404,
    normalize_contact_id,
    is_lead_editable,
    normalize_owner_fields,
    prepare_script_content,
    previous_monday_cutoff,
    APP_TIMEZONE,
)
from helpers.linkedin_helpers import (
    determine_business_status as _determine_business_status,
    filter_templates_by_contact_type as _filter_templates_by_contact_type,
    filter_connection_request_templates as _filter_connection_request_templates,
    filter_accepted_message_templates as _filter_accepted_message_templates,
    filter_inmail_templates as _filter_inmail_templates,
    determine_linkedin_outcome as _determine_linkedin_outcome,
)
from helpers.filter_helpers import (
    build_count_filter,
    build_lead_filters,
    build_filter_query_string,
    lead_navigation_info,
)
from helpers.phone_scripts import load_phone_scripts, get_phone_scripts_json
from helpers.print_log_helpers import get_print_logs_for_lead, serialize_print_log
from services.journey_service import (
    initialize_lead_journey,
    backfill_journey_milestones,
    link_attempt_to_milestone,
    update_milestone_statuses,
    get_journey_status_summary,
    get_journey_data,
    check_prerequisite_milestones,
    link_attempt_to_connection_message_path,
    link_attempt_to_inmail_path,
    link_attempt_to_email_path,
    link_attempt_to_mail_path,
    get_all_linkedin_attempts_position,
    get_connection_message_sequence_position,
    get_email_sequence_position,
    get_mail_sequence_position,
    is_nth_message_attempt,
    cleanup_invalid_milestones,
)
from services.property_service import (
    get_available_years,
    get_property_table_for_year,
    build_property_select,
    get_property_by_id,
    get_property_by_raw_hash,
    get_property_by_order,
    get_property_details_for_lead,
    get_raw_hash_for_order,
    set_property_assignment,
    mark_property_assigned,
    unmark_property_if_unused,
    sync_existing_property_assignments,
    property_navigation_info,
    build_gpt_payload,
    DEFAULT_YEAR,
    PROPERTY_MIN_AMOUNT,
)

Base.metadata.create_all(
    bind=engine,
    tables=[
        BusinessLead.__table__,
        LeadContact.__table__,
        LeadAttempt.__table__,
        LeadComment.__table__,
        ScheduledEmail.__table__,
        PrintLog.__table__,
        LeadJourney.__table__,
        JourneyMilestone.__table__,
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
    # LinkedIn templates are now handled in routers.linkedin module
    from routers import linkedin as linkedin_router
    from pathlib import Path
    linkedin_templates_json = Path(__file__).parent / "templates" / "linkedin" / "templates.json"
    if linkedin_templates_json.exists():
        # Trigger preload by calling the function (it uses internal caching)
        metadata, content = linkedin_router._preload_linkedin_templates()
        count = len(content) if content else 0
        print(f"✓ Pre-loaded {count} LinkedIn templates from JSON into memory")


@app.on_event("shutdown")
def shutdown_scheduler():
    stop_scheduler()


# Register template filter
templates.env.filters["currency"] = format_currency

# Share templates instance with routers (so they have access to filters)
# This must be done after templates is created and filter is registered
routers.leads.templates = templates
routers.contacts.templates = templates
routers.properties.templates = templates

# Register routers
app.include_router(properties_router.router)
app.include_router(leads_router.router)
app.include_router(contacts_router.router)
app.include_router(linkedin_router.router)
app.include_router(emails_router.router)
app.include_router(attempts_router.router)
app.include_router(journey_api_router.router)



# get_db moved to db.py - imported above

PAGE_SIZE = 20
# Constants moved to services.property_service - imported above

# Cache for discovered year tables
_YEAR_TABLES_LIST = None


# Property functions moved to services.property_service - using aliases for backward compatibility
_get_available_years = get_available_years
_get_property_table_for_year = get_property_table_for_year


# Legacy constants for backward compatibility (will be replaced with dynamic table)
PROPERTY_AMOUNT_FILTER = PropertyView.propertyamount >= PROPERTY_MIN_AMOUNT
PROPERTY_ORDERING = (
    PropertyView.propertyamount.desc(),
    PropertyView.raw_hash.asc(),
)

# APP_TIMEZONE moved to utils.datetime_helpers, imported above

# Phone scripts moved to helpers.phone_scripts - imported above
PHONE_SCRIPTS = load_phone_scripts()
PHONE_SCRIPTS_JSON = get_phone_scripts_json()

# Regex patterns moved to utils.html_processing


# HTML processing functions moved to utils.html_processing
# Only _prepare_script_content is used here, imported above


# Date/time and validation helpers moved to utils
_previous_monday_cutoff = previous_monday_cutoff
_is_lead_editable = is_lead_editable


# ---------- VALIDATION HELPERS ----------
# Functions moved to utils.validators - using aliases for backward compatibility
_get_lead_or_404 = get_lead_or_404
_get_contact_or_404 = get_contact_or_404
_normalize_contact_id = normalize_contact_id


# ---------- ATTEMPT NUMBER HELPERS ----------

from utils import get_next_attempt_number as _get_next_attempt_number


# ---------- OWNER FIELDS NORMALIZATION ----------
# Function moved to utils.normalizers - using alias for backward compatibility
_normalize_owner_fields = normalize_owner_fields


# ---------- LINKEDIN HELPERS ----------
# Functions moved to helpers.linkedin_helpers - already imported above with _ prefix aliases

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


# Property functions moved to services.property_service - using aliases for backward compatibility
_mark_property_assigned = mark_property_assigned
_set_property_assignment = set_property_assignment
_unmark_property_if_unused = unmark_property_if_unused
_sync_existing_property_assignments = sync_existing_property_assignments
_build_property_select = build_property_select
_get_property_by_id = get_property_by_id
_get_property_by_order = get_property_by_order
_get_property_by_raw_hash = get_property_by_raw_hash
_get_property_details_for_lead = get_property_details_for_lead
_get_raw_hash_for_order = get_raw_hash_for_order


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


# Print log helpers moved to helpers.print_log_helpers - imported above
_serialize_print_log = serialize_print_log
_get_print_logs_for_lead = get_print_logs_for_lead


# Filter helpers moved to helpers.filter_helpers - using aliases for backward compatibility
_build_count_filter = build_count_filter


# ---------- JOURNEY TRACKING HELPERS ----------
# Functions moved to services.journey_service - using aliases for backward compatibility
_initialize_lead_journey = initialize_lead_journey
_backfill_journey_milestones = backfill_journey_milestones
_link_attempt_to_milestone = link_attempt_to_milestone
_update_milestone_statuses = update_milestone_statuses
_get_journey_status_summary = get_journey_status_summary
_get_journey_data = get_journey_data
_check_prerequisite_milestones = check_prerequisite_milestones
_link_attempt_to_connection_message_path = link_attempt_to_connection_message_path
_link_attempt_to_inmail_path = link_attempt_to_inmail_path
_link_attempt_to_email_path = link_attempt_to_email_path
_link_attempt_to_mail_path = link_attempt_to_mail_path
_get_all_linkedin_attempts_position = get_all_linkedin_attempts_position
_get_connection_message_sequence_position = get_connection_message_sequence_position
_get_email_sequence_position = get_email_sequence_position
_get_mail_sequence_position = get_mail_sequence_position
_is_nth_message_attempt = is_nth_message_attempt
_cleanup_invalid_milestones = cleanup_invalid_milestones

# Legacy function definitions removed - now imported from services.journey_service


# Filter and navigation helpers moved to helpers.filter_helpers - using aliases for backward compatibility
_build_lead_filters = build_lead_filters
_build_filter_query_string = build_filter_query_string
_lead_navigation_info = lead_navigation_info


# Property navigation and GPT payload functions moved to services.property_service - using aliases for backward compatibility
_property_navigation_info = property_navigation_info
_build_gpt_payload = build_gpt_payload

# All lead routes have been moved to routers:
# - routers.leads: Core lead CRUD, list, view, edit, bulk actions, entity intel
# - routers.contacts: Contact management, mark primary, letters, prep email
# - routers.linkedin: LinkedIn templates, preview, mark sent, connection accepted
# - routers.emails: Send email, schedule email, manage scheduled emails
# - routers.attempts: Create attempts, comments, print logs
# - routers.journey_api: Journey tracking API endpoints

# Old route definitions removed - see routers/ directory for implementation
