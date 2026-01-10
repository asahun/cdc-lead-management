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


def is_competitor_claimed(lead: Lead) -> bool:
    """
    Check if a lead should be considered competitor_claimed.
    This is computed from properties: all properties must be deleted_from_source.
    
    Args:
        lead: The Lead instance (must have properties loaded)
        
    Returns:
        True if all properties are deleted_from_source, False otherwise
    """
    if not lead.properties:
        return False  # No properties means not claimed
    
    # All properties must be deleted for the lead to be considered claimed
    return all(prop.deleted_from_source for prop in lead.properties)


def is_partially_claimed(lead: Lead) -> bool:
    """
    Check if a lead has some (but not all) properties deleted.
    
    Args:
        lead: The Lead instance (must have properties loaded)
        
    Returns:
        True if some properties are deleted but not all, False otherwise
    """
    if not lead.properties:
        return False  # No properties means not partially claimed
    
    deleted_count = sum(1 for prop in lead.properties if prop.deleted_from_source)
    total_count = len(lead.properties)
    
    # Partially claimed if some are deleted but not all
    return 0 < deleted_count < total_count


def get_effective_status(lead: Lead) -> LeadStatus | str:
    """
    Get the effective status of a lead, including computed competitor_claimed and partially_claimed statuses.
    
    - If all properties are deleted_from_source, returns "competitor_claimed"
    - If some (but not all) properties are deleted, returns "partially_claimed"
    - Otherwise, returns the stored LeadStatus enum value
    
    Args:
        lead: The Lead instance (must have properties loaded)
        
    Returns:
        LeadStatus | str - the effective status (may be computed string status)
    """
    if is_competitor_claimed(lead):
        return "competitor_claimed"
    if is_partially_claimed(lead):
        return "partially_claimed"
    return lead.status


def is_lead_editable(lead: Lead) -> bool:
    """
    Determine if a lead can be edited. Returns False if all properties are deleted.
    """
    # Lead is read-only if all properties are deleted (competitor_claimed)
    return not is_competitor_claimed(lead)

