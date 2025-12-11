"""
Email routes - handles email sending and scheduled email management.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from db import get_db
from models import (
    BusinessLead,
    LeadContact,
    LeadAttempt,
    ContactChannel,
    ScheduledEmail,
    ScheduledEmailStatus,
)
from services.journey_service import link_attempt_to_milestone
from utils import get_lead_or_404, get_contact_or_404, get_next_attempt_number
from services.email_service import (
    send_email,
    resolve_profile,
    embed_profile_marker,
    extract_profile_marker,
)

router = APIRouter()


@router.post("/leads/{lead_id}/contacts/{contact_id}/send-email")
def send_contact_email(
    lead_id: int,
    contact_id: int,
    subject: str = Form(...),
    body: str = Form(...),
    profile: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Send email to a contact and create attempt record."""
    lead = get_lead_or_404(db, lead_id)
    contact = get_contact_or_404(db, contact_id, lead_id)
    
    if not contact.email:
        raise HTTPException(status_code=400, detail="Contact has no email address")
    
    try:
        profile_config = resolve_profile(profile)
        send_email(
            to_email=contact.email,
            subject=subject,
            html_body=body,
            from_email=profile_config["from_email"],
            from_name=profile_config["from_name"],
            reply_to=profile_config["reply_to"],
            smtp_username=profile_config["from_email"],
            smtp_password=profile_config.get("smtp_password") or None,
        )
        
        next_attempt_number = get_next_attempt_number(db, lead_id)
        
        attempt = LeadAttempt(
            lead_id=lead.id,
            contact_id=contact.id,
            channel=ContactChannel.email,
            attempt_number=next_attempt_number,
            outcome="Email sent",
            notes=f"Subject: {subject[:100]}",
        )
        db.add(attempt)
        db.flush()
        
        link_attempt_to_milestone(db, attempt)
        
        db.commit()
        
        return JSONResponse(content={"status": "success", "message": "Email sent successfully"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


@router.post("/leads/{lead_id}/contacts/{contact_id}/schedule-email")
def schedule_contact_email(
    lead_id: int,
    contact_id: int,
    subject: str = Form(...),
    body: str = Form(...),
    scheduled_at: str = Form(...),
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
        scheduled_datetime = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        if scheduled_datetime.tzinfo is None:
            scheduled_datetime = scheduled_datetime.replace(tzinfo=timezone.utc)
        
        if scheduled_datetime <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Scheduled time must be in the future")
        
        profile_config = resolve_profile(profile)
        body_with_marker = embed_profile_marker(body, profile_config["key"])
        
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


@router.get("/leads/{lead_id}/scheduled-emails")
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


@router.get("/leads/{lead_id}/scheduled-emails/{scheduled_id}")
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


@router.post("/leads/{lead_id}/scheduled-emails/{scheduled_id}/send-now")
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
        
        send_email(
            to_email=scheduled_email.to_email,
            subject=scheduled_email.subject,
            html_body=clean_body,
            from_email=profile_config["from_email"],
            from_name=profile_config["from_name"],
            reply_to=profile_config["reply_to"],
            smtp_username=profile_config["from_email"],
            smtp_password=profile_config.get("smtp_password") or None,
        )
        
        scheduled_email.status = ScheduledEmailStatus.sent
        scheduled_email.sent_at = datetime.now(timezone.utc)
        db.commit()
        
        next_attempt_number = get_next_attempt_number(db, lead_id)
        
        attempt = LeadAttempt(
            lead_id=lead_id,
            contact_id=scheduled_email.contact_id,
            channel=ContactChannel.email,
            attempt_number=next_attempt_number,
            outcome="Email sent (scheduled, sent now)",
            notes=f"Originally scheduled for {scheduled_email.scheduled_at.isoformat()}. Subject: {scheduled_email.subject[:100]}",
        )
        db.add(attempt)
        db.flush()
        
        link_attempt_to_milestone(db, attempt)
        
        db.commit()
        
        return JSONResponse(content={"status": "success", "message": "Email sent successfully"})
    except Exception as e:
        db.rollback()
        scheduled_email.status = ScheduledEmailStatus.failed
        scheduled_email.error_message = str(e)[:500]
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


@router.put("/leads/{lead_id}/scheduled-emails/{scheduled_id}")
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


@router.delete("/leads/{lead_id}/scheduled-emails/{scheduled_id}")
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

