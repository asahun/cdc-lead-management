# main.py
import json

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from db import Base, engine
from models import (
    Lead,
    LeadProperty,
    LeadContact,
    LeadAttempt,
    LeadComment,
    ScheduledEmail,
    PrintLog,
    LeadJourney,
    JourneyMilestone,
)

from services.email_service import PROFILE_REGISTRY
from services.email_scheduler import start_scheduler, stop_scheduler
from services.property_service import sync_existing_property_assignments
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
from utils import format_currency
from helpers.phone_scripts import load_phone_scripts, get_phone_scripts_json

# Create database tables
Base.metadata.create_all(
    bind=engine,
    tables=[
        Lead.__table__,
        LeadProperty.__table__,
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
    sync_existing_property_assignments()
    start_scheduler()
    # Pre-load LinkedIn templates from JSON at startup for instant access
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

# Load phone scripts for template globals
PHONE_SCRIPTS = load_phone_scripts()
PHONE_SCRIPTS_JSON = get_phone_scripts_json()

# Build profile UI data for template globals
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
