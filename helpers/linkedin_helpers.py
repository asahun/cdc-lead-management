"""
LinkedIn-specific helper functions for template filtering and outcome determination.
"""

from models import BusinessLead, LeadContact, ContactType, BusinessOwnerStatus


def determine_business_status(lead: BusinessLead) -> str:
    """Determine business status string from lead."""
    if lead.business_owner_status == BusinessOwnerStatus.dissolved:
        return "dissolved"
    elif lead.business_owner_status in (BusinessOwnerStatus.acquired_or_merged, BusinessOwnerStatus.active_renamed):
        return "acquired"
    elif lead.business_owner_status == BusinessOwnerStatus.active:
        return "active"
    return "active"  # Default


def filter_templates_by_contact_type(
    templates: list[dict],
    contact_type: ContactType,
    business_status: str
) -> list[dict]:
    """Filter templates by contact type and business status."""
    if contact_type == ContactType.agent:
        return [t for t in templates if t.get("contact_type") == "agent"]
    else:
        return [
            t for t in templates
            if t.get("contact_type") == "leader" and (
                t.get("business_status") == business_status or
                t.get("business_status") is None
            )
        ]


def filter_connection_request_templates(
    templates: dict,
    contact: LeadContact,
    business_status: str,
    can_send: bool
) -> list[dict]:
    """Filter connection request templates."""
    if not can_send:
        return []
    return filter_templates_by_contact_type(
        templates.get("connection_requests", []),
        contact.contact_type,
        business_status
    )


def filter_accepted_message_templates(
    templates: dict,
    contact: LeadContact,
    business_status: str,
    connection_status: dict
) -> list[dict]:
    """Filter accepted message templates to show only next message."""
    if not connection_status["can_send_messages"]:
        return []
    
    all_messages = filter_templates_by_contact_type(
        templates.get("accepted_messages", []),
        contact.contact_type,
        business_status
    )
    
    if connection_status["next_message_number"]:
        return [
            t for t in all_messages
            if t.get("attempt") == f"followup_{connection_status['next_message_number']}"
        ]
    return []


def filter_inmail_templates(
    templates: dict,
    contact: LeadContact,
    business_status: str,
    connection_status: dict
) -> list[dict]:
    """Filter InMail templates with fallback logic."""
    if not connection_status["can_send_inmail"] or connection_status.get("inmail_sent", False):
        return []
    
    if contact.contact_type == ContactType.agent:
        return []
    
    all_inmail = templates.get("inmail", [])
    
    # Try exact match
    for t in all_inmail:
        if t.get("business_status") == business_status:
            return [t]
    
    # Try active as fallback
    for t in all_inmail:
        if t.get("business_status") == "active":
            return [t]
    
    # Final fallback
    return [all_inmail[0]] if all_inmail else []


def determine_linkedin_outcome(template_category: str, template_name: str) -> str:
    """Determine LinkedIn attempt outcome from template category and name."""
    OUTCOME_MAP = {
        "connection_requests": "Connection Request Sent",
        "inmail": "InMail Sent",
    }
    
    if template_category in OUTCOME_MAP:
        return OUTCOME_MAP[template_category]
    
    if template_category == "accepted_messages":
        # Extract message number from template name
        for num in ["1", "2", "3"]:
            if f"message_{num}" in template_name or f"followup_{num}" in template_name:
                return f"LinkedIn Message {num} Sent"
        return "LinkedIn Message Sent"
    
    return "LinkedIn Message Sent"  # Default fallback

