"""
Journey API routes - handles journey tracking API endpoints.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from db import get_db
from models import (
    BusinessLead,
    LeadStatus,
    LeadAttempt,
    LeadJourney,
    JourneyMilestone,
    MilestoneStatus,
)
from services.journey_service import (
    get_journey_data,
    get_journey_status_summary,
    link_attempt_to_milestone,
    check_prerequisite_milestones,
    cleanup_invalid_milestones,
)
from utils import get_lead_or_404

router = APIRouter()


@router.get("/api/leads/{lead_id}/journey")
def get_lead_journey(
    lead_id: int,
    db: Session = Depends(get_db),
    debug: bool = Query(False, description="Include debug information"),
):
    """Get journey data for a lead."""
    lead = get_lead_or_404(db, lead_id)
    
    journey_hidden_statuses = {
        LeadStatus.new,
        LeadStatus.researching,
        LeadStatus.invalid,
        LeadStatus.competitor_claimed
    }
    
    if lead.status in journey_hidden_statuses:
        return JSONResponse(
            content={"error": f"Journey is not available for leads with status '{lead.status.value}'"},
            status_code=400
        )
    
    journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
    if not journey:
        return JSONResponse(
            content={"error": "Journey not available. Please mark a contact as primary first."},
            status_code=400
        )
    
    journey_data = get_journey_data(db, lead_id)
    
    if debug:
        all_attempts = db.query(LeadAttempt).filter(
            LeadAttempt.lead_id == lead_id
        ).order_by(LeadAttempt.created_at.asc()).all()
        
        primary_attempts = []
        if journey.primary_contact_id:
            primary_attempts = db.query(LeadAttempt).filter(
                LeadAttempt.lead_id == lead_id,
                LeadAttempt.contact_id == journey.primary_contact_id
            ).order_by(LeadAttempt.created_at.asc()).all()
        
        journey_data["_debug"] = {
            "journey_id": journey.id,
            "primary_contact_id": journey.primary_contact_id,
            "started_at": journey.started_at.isoformat() if journey.started_at else None,
            "total_attempts": len(all_attempts),
            "primary_contact_attempts": len(primary_attempts),
            "all_attempts": [
                {
                    "id": a.id,
                    "contact_id": a.contact_id,
                    "channel": a.channel.value,
                    "outcome": a.outcome,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in all_attempts[:10]
            ],
            "primary_attempts": [
                {
                    "id": a.id,
                    "contact_id": a.contact_id,
                    "channel": a.channel.value,
                    "outcome": a.outcome,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in primary_attempts[:10]
            ],
        }
    
    return JSONResponse(content=journey_data)


@router.post("/api/leads/{lead_id}/journey/relink-attempts")
def relink_attempts_to_milestones(
    lead_id: int,
    db: Session = Depends(get_db),
):
    """Manually relink existing attempts to milestones. Useful for fixing missed links.
    Also fixes discrepancies by unlinking milestones that violate prerequisites."""
    lead = get_lead_or_404(db, lead_id)
    
    journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
    if not journey:
        return JSONResponse(
            content={"error": "Journey not found. Please mark a contact as primary first."},
            status_code=400
        )
    
    if not journey.primary_contact_id:
        return JSONResponse(
            content={"error": "Journey has no primary contact set."},
            status_code=400
        )
    
    cleanup_invalid_milestones(db, journey.id)
    
    all_milestones = db.query(JourneyMilestone).filter(
        JourneyMilestone.journey_id == journey.id
    ).all()
    
    unlinked_count = 0
    for milestone in all_milestones:
        if milestone.status == MilestoneStatus.completed and milestone.attempt_id:
            if not check_prerequisite_milestones(db, journey.id, milestone.milestone_type):
                milestone.status = MilestoneStatus.pending
                milestone.completed_at = None
                milestone.attempt_id = None
                milestone.updated_at = datetime.now(timezone.utc)
                unlinked_count += 1
    
    attempts = db.query(LeadAttempt).filter(
        LeadAttempt.lead_id == lead_id,
        LeadAttempt.contact_id == journey.primary_contact_id
    ).order_by(LeadAttempt.created_at.asc()).all()
    
    for attempt in attempts:
        existing_link = db.query(JourneyMilestone).filter(
            JourneyMilestone.attempt_id == attempt.id
        ).first()
        if existing_link:
            existing_link.status = MilestoneStatus.pending
            existing_link.completed_at = None
            existing_link.attempt_id = None
            existing_link.updated_at = datetime.now(timezone.utc)
    
    db.flush()
    
    linked_count = 0
    for attempt in attempts:
        db.expire_all()
        link_attempt_to_milestone(db, attempt)
        linked = db.query(JourneyMilestone).filter(
            JourneyMilestone.attempt_id == attempt.id
        ).first()
        if linked:
            linked_count += 1
            db.commit()
    
    db.commit()
    
    return JSONResponse(content={
        "status": "success",
        "message": f"Processed {len(attempts)} attempts, unlinked {unlinked_count} invalid links, linked {linked_count} to milestones"
    })


@router.post("/api/leads/batch/journey-status")
async def get_batch_journey_status(
    request: Request,
    db: Session = Depends(get_db),
):
    """Get journey status summaries for multiple leads (for list view indicators)."""
    body = await request.json()
    lead_ids = body.get("lead_ids", [])
    
    if not lead_ids:
        return JSONResponse(content={})
    
    status_map = {}
    journey_hidden_statuses = {
        LeadStatus.new,
        LeadStatus.researching,
        LeadStatus.invalid,
        LeadStatus.competitor_claimed
    }
    
    for lead_id in lead_ids:
        lead = db.get(BusinessLead, lead_id)
        if not lead or lead.status in journey_hidden_statuses:
            continue
        
        summary = get_journey_status_summary(db, lead_id)
        if summary:
            status_map[str(lead_id)] = summary
    
    return JSONResponse(content=status_map)

