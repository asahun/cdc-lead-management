"""
Lead bulk actions.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from db import get_db
from models import ContactChannel, Lead, LeadAttempt, LeadStatus, PrintLog
from services.journey_service import link_attempt_to_milestone
from utils import get_next_attempt_number, is_lead_editable

router = APIRouter()


@router.post("/leads/bulk/change-status")
async def bulk_change_status(
    request: Request,
    db: Session = Depends(get_db),
):
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

    return JSONResponse(
        content={"updated": updated, "skipped": skipped, "total": len(lead_ids)}
    )


@router.post("/leads/bulk/mark-mail-sent")
async def bulk_mark_mail_sent(
    request: Request,
    db: Session = Depends(get_db),
):
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

        unmailed_logs = (
            db.query(PrintLog)
            .filter(PrintLog.lead_id == lead_id, PrintLog.mailed == False)
            .all()
        )

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

    return JSONResponse(
        content={
            "leads_processed": leads_processed,
            "print_logs_marked": print_logs_marked,
            "attempts_created": attempts_created,
            "skipped": skipped,
            "total": len(lead_ids),
        }
    )
