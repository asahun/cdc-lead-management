"""
LinkedIn routes - handles LinkedIn-specific endpoints for leads and contacts.
"""

from datetime import datetime, timezone
from pathlib import Path
import json

from fastapi import APIRouter, Depends, Request, Form, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from db import get_db
from models import BusinessLead, LeadContact, LeadAttempt, ContactChannel
from services.property_service import get_property_details_for_lead
from services.journey_service import link_attempt_to_milestone
from utils import get_lead_or_404, get_contact_or_404, get_next_attempt_number
from helpers.linkedin_helpers import (
    determine_business_status,
    filter_connection_request_templates,
    filter_accepted_message_templates,
    filter_inmail_templates,
    determine_linkedin_outcome,
)
from services.email_service import resolve_profile, _build_template_context

# LinkedIn template loading
LINKEDIN_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "linkedin"
LINKEDIN_TEMPLATES_JSON = LINKEDIN_TEMPLATE_DIR / "templates.json"

# Cache templates metadata and content to avoid file I/O on every request
_LINKEDIN_TEMPLATES_METADATA_CACHE = None
_LINKEDIN_TEMPLATES_CONTENT_CACHE = None


def _load_linkedin_templates_from_json() -> tuple[dict, dict]:
    """
    Load LinkedIn templates from JSON file.
    Returns (metadata_dict, content_dict) where:
    - metadata_dict: structured like the old discovery format for compatibility
    - content_dict: template_name -> content mapping
    """
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
        if "agent" in cr_data:
            template = cr_data["agent"].copy()
            template["name"] = "agent_connection_request.txt"
            metadata["connection_requests"].append(template)
            content_cache["agent_connection_request.txt"] = template["content"]
        
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
    
    # Sort for consistent ordering
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
        "last_message_number": int | None,
        "can_send_connection": bool,
        "can_send_messages": bool,
        "can_send_inmail": bool,
        "next_message_number": int | None,
        "all_followups_complete": bool
    }
    """
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
        
        if "Connection Accepted" in outcome:
            is_connected = True
        elif "Connection Request Sent" in outcome:
            has_connection_request = True
        
        if "InMail Sent" in outcome or "inmail" in outcome.lower():
            inmail_sent = True
        
        if "Message 1" in outcome or "Follow-up 1" in outcome:
            if last_message_number is None:
                last_message_number = 1
        elif "Message 2" in outcome or "Follow-up 2" in outcome:
            if last_message_number is None or last_message_number < 2:
                last_message_number = 2
        elif "Message 3" in outcome or "Follow-up 3" in outcome:
            if last_message_number is None or last_message_number < 3:
                last_message_number = 3
    
    can_send_connection = not has_connection_request and not is_connected
    can_send_messages = is_connected
    can_send_inmail = has_connection_request and not is_connected and not inmail_sent
    
    all_followups_complete = False
    if is_connected:
        if last_message_number is None:
            next_message_number = 1
        elif last_message_number < 3:
            next_message_number = last_message_number + 1
        else:
            next_message_number = None
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


router = APIRouter()


@router.get("/leads/{lead_id}/linkedin-templates")
def get_linkedin_templates(
    lead_id: int,
    contact_id: int = Query(None, description="Contact ID to filter templates by contact type"),
    db: Session = Depends(get_db),
):
    """Get list of available LinkedIn templates, filtered by contact type and connection status."""
    lead = get_lead_or_404(db, lead_id)
    
    if not contact_id:
        return JSONResponse(content={"templates": _get_linkedin_templates_metadata()})
    
    contact = get_contact_or_404(db, contact_id, lead_id)
    connection_status = _get_linkedin_connection_status(db, contact_id)
    business_status = determine_business_status(lead)
    templates = _get_linkedin_templates_metadata()
    
    return JSONResponse(content={
        "templates": {
            "connection_requests": filter_connection_request_templates(
                templates, contact, business_status, connection_status["can_send_connection"]
            ),
            "accepted_messages": filter_accepted_message_templates(
                templates, contact, business_status, connection_status
            ),
            "inmail": filter_inmail_templates(
                templates, contact, business_status, connection_status
            ),
        },
        "connection_status": connection_status
    })


@router.get("/leads/{lead_id}/contacts/{contact_id}/linkedin-preview")
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
    
    prop = get_property_details_for_lead(db, lead)
    
    profile_data = resolve_profile(profile)
    
    context = _build_template_context(lead, contact, prop, profile=profile_data)
    
    content = _get_linkedin_template_content(template_name)
    if not content:
        raise HTTPException(status_code=404, detail=f"Template {template_name} not found")
    
    subject = None
    body = content
    if content.startswith("Subject:"):
        lines = content.split("\n", 1)
        subject_line = lines[0].replace("Subject:", "").strip()
        body = lines[1].strip() if len(lines) == 2 else ""
        for key, value in context.items():
            placeholder = f"[{key}]"
            subject_line = subject_line.replace(placeholder, str(value) if value else "")
        subject = subject_line
    
    for key, value in context.items():
        placeholder = f"[{key}]"
        body = body.replace(placeholder, str(value) if value else "")
    
    response_data = {"preview": body}
    if subject:
        response_data["subject"] = subject
        response_data["has_subject"] = True
    
    return JSONResponse(content=response_data)


@router.post("/leads/{lead_id}/contacts/{contact_id}/linkedin-mark-sent")
def mark_linkedin_message_sent(
    lead_id: int,
    contact_id: int,
    template_name: str = Form(..., description="Template filename"),
    template_category: str = Form(..., description="Template category: connection_requests, accepted_messages, or inmail"),
    db: Session = Depends(get_db),
):
    """Mark a LinkedIn message as sent and create an attempt record."""
    lead = get_lead_or_404(db, lead_id)
    contact = get_contact_or_404(db, contact_id, lead_id)
    
    outcome = determine_linkedin_outcome(template_category, template_name)
    
    next_attempt_number = get_next_attempt_number(db, lead_id)
    
    attempt = LeadAttempt(
        lead_id=lead.id,
        contact_id=contact.id,
        channel=ContactChannel.linkedin,
        attempt_number=next_attempt_number,
        outcome=outcome,
        notes=f"Template: {template_name}",
    )
    db.add(attempt)
    db.flush()
    
    link_attempt_to_milestone(db, attempt)
    
    db.commit()
    
    return JSONResponse(content={
        "status": "success",
        "message": "LinkedIn message marked as sent",
        "attempt_id": attempt.id
    })


@router.post("/leads/{lead_id}/contacts/{contact_id}/linkedin-connection-accepted")
def mark_linkedin_connection_accepted(
    lead_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    """Mark LinkedIn connection as accepted and create an attempt record."""
    lead = get_lead_or_404(db, lead_id)
    contact = get_contact_or_404(db, contact_id, lead_id)
    
    next_attempt_number = get_next_attempt_number(db, lead_id)
    
    attempt = LeadAttempt(
        lead_id=lead.id,
        contact_id=contact.id,
        channel=ContactChannel.linkedin,
        attempt_number=next_attempt_number,
        outcome="Connection Accepted",
        notes="LinkedIn connection request was accepted",
    )
    db.add(attempt)
    db.flush()
    
    link_attempt_to_milestone(db, attempt)
    
    db.commit()
    
    return JSONResponse(content={
        "status": "success",
        "message": "LinkedIn connection marked as accepted",
        "attempt_id": attempt.id
    })

