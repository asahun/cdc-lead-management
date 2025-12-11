"""
Attempts, comments, and print log routes.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from db import get_db
from models import (
    BusinessLead,
    LeadContact,
    LeadAttempt,
    LeadComment,
    ContactChannel,
    PrintLog,
    LeadAttempt as LeadAttemptModel,
)
from services.journey_service import link_attempt_to_milestone
from utils import get_lead_or_404, normalize_contact_id, get_next_attempt_number
from helpers.print_log_helpers import get_print_logs_for_lead, serialize_print_log

router = APIRouter()


@router.get("/leads/{lead_id}/attempts", response_class=HTMLResponse)
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


@router.post("/leads/{lead_id}/attempts/create")
def create_lead_attempt(
    lead_id: int,
    channel: ContactChannel = Form(...),
    contact_id: str | None = Form(None),
    outcome: str | None = Form(None),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)

    contact_id_val = normalize_contact_id(contact_id)

    next_attempt_number = get_next_attempt_number(db, lead_id)

    attempt = LeadAttempt(
        lead_id=lead.id,
        contact_id=contact_id_val,
        channel=channel,
        attempt_number=next_attempt_number,
        outcome=outcome,
        notes=notes,
    )
    db.add(attempt)
    db.flush()
    
    link_attempt_to_milestone(db, attempt)
    
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit#attempts", status_code=303)


@router.post("/leads/{lead_id}/comments/create")
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


@router.post("/leads/{lead_id}/comments/{comment_id}/delete")
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


@router.get("/leads/{lead_id}/print-logs")
def list_print_logs(
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    logs = get_print_logs_for_lead(db, lead_id)
    return {"logs": [serialize_print_log(log) for log in logs]}


@router.post("/leads/{lead_id}/print-logs/{log_id}/mark-mailed")
def mark_print_log_as_mailed(
    lead_id: int,
    log_id: int,
    db: Session = Depends(get_db),
):
    log = db.get(PrintLog, log_id)
    if not log or log.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Print log not found")

    if log.mailed:
        return serialize_print_log(log)

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
    db.commit()
    db.refresh(log)

    return serialize_print_log(log)


@router.delete("/leads/{lead_id}/print-logs/{log_id}")
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

