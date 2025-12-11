"""
Helper functions for attempt numbering and management.
"""

from sqlalchemy.orm import Session
from sqlalchemy import func

from models import LeadAttempt


def get_next_attempt_number(db: Session, lead_id: int) -> int:
    """
    Get the next attempt number for a lead.
    Returns 1 if no attempts exist, otherwise returns max(attempt_number) + 1.
    """
    max_attempt = db.query(func.max(LeadAttempt.attempt_number)).filter(
        LeadAttempt.lead_id == lead_id
    ).scalar()
    
    if max_attempt is None:
        return 1
    return max_attempt + 1

