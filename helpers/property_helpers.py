"""
Property helpers for lead-property relationships.
"""
from typing import Optional
from models import Lead, LeadProperty


def get_primary_property(lead: Lead) -> Optional[LeadProperty]:
    """
    Get the primary property for a lead.
    
    Returns the property marked as primary, or the first property if none is marked primary.
    Returns None if the lead has no properties.
    
    Args:
        lead: The Lead instance
        
    Returns:
        LeadProperty instance if found, None otherwise
    """
    if not lead.properties:
        return None
    
    # Find primary property
    primary = next((p for p in lead.properties if p.is_primary), None)
    if primary:
        return primary
    
    # Fallback to first property (by added_at, which is the default order)
    return lead.properties[0] if lead.properties else None

