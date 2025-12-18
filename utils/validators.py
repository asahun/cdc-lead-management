"""
Validation helpers for database lookups and data validation.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Lead, LeadContact, LeadStatus


def get_lead_or_404(db: Session, lead_id: int) -> Lead:
    """Get lead by ID or raise 404 HTTPException."""
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def get_contact_or_404(db: Session, contact_id: int, lead_id: int) -> LeadContact:
    """Get contact by ID or raise 404 HTTPException, ensuring it belongs to the lead."""
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


def normalize_contact_id(contact_id: str | None) -> int | None:
    """Normalize contact_id from form (empty string -> None, otherwise int)."""
    if not contact_id:
        return None
    return int(contact_id)


def is_lead_editable(lead: Lead) -> bool:
    """
    Determine if a lead can be edited. Returns False for terminal/archived statuses.
    """
    read_only_statuses = {LeadStatus.competitor_claimed}
    return lead.status not in read_only_statuses

