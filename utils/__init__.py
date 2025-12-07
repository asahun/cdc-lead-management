"""
Utility helpers shared across the application.
"""

from sqlalchemy.orm import Session
from sqlalchemy import select

from models import LeadAttempt


def get_next_attempt_number(db: Session, lead_id: int) -> int:
    """
    Calculate the next attempt number for a lead.
    
    This is a shared utility function that can be imported by both main.py
    and email_scheduler.py to avoid code duplication.
    """
    last_attempt = db.scalar(
        select(LeadAttempt)
        .where(LeadAttempt.lead_id == lead_id)
        .order_by(LeadAttempt.attempt_number.desc())
        .limit(1)
    )
    return (last_attempt.attempt_number + 1) if last_attempt else 1

