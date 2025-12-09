"""
Email sending functionality for lead contacts.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from typing import Optional, Dict, Any
from pathlib import Path
from decimal import Decimal

from sqlalchemy.orm import Session

from models import BusinessLead, LeadContact, PropertyView, BusinessOwnerStatus, OwnerType
from utils.name_utils import format_first_name


# SMTP Configuration (IONIO)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.ionos.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates" / "email"

# Profile configuration
PROFILES_ENV_DEFAULTS = {
    "fisseha": {
        "label": "Fisseha",
        "first_name": os.getenv("EMAIL_PROFILE_FISSEHA_FIRST", "Fisseha"),
        "last_name": os.getenv("EMAIL_PROFILE_FISSEHA_LAST", "Gebresilasie"),
        "full_name": os.getenv("EMAIL_PROFILE_FISSEHA_NAME", "Fisseha Gebresilasie"),
        "from_email": os.getenv("EMAIL_PROFILE_FISSEHA_FROM", "fisseha@loadrouter.com"),
        "reply_to": os.getenv("EMAIL_PROFILE_FISSEHA_REPLY_TO", "fisseha@loadrouter.com"),
        "phone": os.getenv("EMAIL_PROFILE_FISSEHA_PHONE", "(404) 654-3593"),
        "title": os.getenv("EMAIL_PROFILE_FISSEHA_TITLE", "Client Relations & Compliance Manager"),
        "signature_template": "signature.html",
        "smtp_password": os.getenv("EMAIL_PROFILE_FISSEHA_PASSWORD", ""),
    },
    "abby": {
        "label": "Abby",
        "first_name": os.getenv("EMAIL_PROFILE_ABBY_FIRST", "Abby"),
        "last_name": os.getenv("EMAIL_PROFILE_ABBY_LAST", "Tezera"),
        "full_name": os.getenv("EMAIL_PROFILE_ABBY_NAME", "Abby Tezera"),
        "from_email": os.getenv("EMAIL_PROFILE_ABBY_FROM", "abby@loadrouter.com"),
        "reply_to": os.getenv("EMAIL_PROFILE_ABBY_REPLY_TO", "abby@loadrouter.com"),
        "phone": os.getenv("EMAIL_PROFILE_ABBY_PHONE", "(678) 250-3198"),
        "title": os.getenv("EMAIL_PROFILE_ABBY_TITLE", "Client Relations & Compliance Manager"),
        "signature_template": "signature.html",
        "smtp_password": os.getenv("EMAIL_PROFILE_ABBY_PASSWORD", ""),
    },
}

PROFILE_REGISTRY = {
    key: {
        **value,
        "from_name": value["full_name"],
    }
    for key, value in PROFILES_ENV_DEFAULTS.items()
}

DEFAULT_PROFILE_KEY = os.getenv("EMAIL_PROFILE_DEFAULT", "abby").lower()

PROFILE_MARKER_PREFIX = "<!--PROFILE:"
PROFILE_MARKER_SUFFIX = "-->"

# Template mapping based on lead status
TEMPLATE_MAP = {
    BusinessOwnerStatus.dissolved: "dissolved_inactive.html",
    BusinessOwnerStatus.acquired_or_merged: "acquired_merged.html",
    BusinessOwnerStatus.active_renamed: "acquired_merged.html",  # Use acquired template for renamed
    BusinessOwnerStatus.active: "active_company.html",
    OwnerType.individual: "Individual.html",
}


def _get_template_name(lead: BusinessLead, template_variant: str = "initial") -> Optional[str]:
    """
    Determine which email template to use based on lead status and variant.
    
    Args:
        lead: The business lead
        template_variant: One of "initial", "followup_1", "followup_2"
    
    Returns:
        Template filename or None if no match
    """
    base_template = None
    
    if lead.owner_type == OwnerType.individual:
        base_template = TEMPLATE_MAP[OwnerType.individual]
    elif lead.owner_type == OwnerType.business and lead.business_owner_status:
        base_template = TEMPLATE_MAP.get(lead.business_owner_status)
    
    if not base_template:
        return None
    
    # Handle template variants
    if template_variant == "initial":
        return base_template
    elif template_variant == "followup_1":
        # Replace .html with _followup_1.html
        return base_template.replace(".html", "_followup_1.html")
    elif template_variant == "followup_2":
        # Replace .html with _followup_2.html
        return base_template.replace(".html", "_followup_2.html")
    
    return base_template


def _extract_first_name(contact_name: str) -> str:
    """Extract normalized first name from a contact."""
    return format_first_name(contact_name)


def _format_amount(amount: Optional[Decimal]) -> str:
    """Format property amount for display."""
    if amount is None:
        return "—"
    return f"${amount:,.2f}"


def _build_template_context(
    lead: BusinessLead,
    contact: LeadContact,
    property_details: Optional[PropertyView],
    profile: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Build context dictionary for template placeholder substitution.
    
    Args:
        lead: The business lead
        contact: The contact
        property_details: Property details (optional)
        profile: Profile configuration (optional, for LinkedIn templates)
    """
    first_name = _extract_first_name(contact.contact_name)
    company_name = lead.owner_name
    new_entity_name = lead.new_business_name or company_name  # Use new entity name if available, otherwise fall back to company name
    
    context = {
        "FirstName": first_name,  # Standardized placeholder for contact's first name (used in all LinkedIn templates)
        "ID": lead.property_id,
        "Company Legal Name": company_name,  # Standardized placeholder for company name (property record name)
        "Company": company_name,  # Alias for Company Legal Name (for shorter usage)
        "Old Entity Legal Name": company_name,  # Same as Company Legal Name (for dissolved/acquired contexts)
        "OldBusinessName": company_name,  # Same as Company Legal Name
        "New Entity Name": new_entity_name,  # Current/active company name (for acquired/merged companies)
    }
    
    # Add profile first name if profile is provided (for LinkedIn templates)
    if profile:
        context["Profile First Name"] = profile.get("first_name", "")
    
    if property_details:
        # Handle both dict and object (PropertyView) cases
        if isinstance(property_details, dict):
            reportyear = property_details.get("reportyear") or ""
            holdername = property_details.get("holdername") or ""
            propertytypedescription = property_details.get("propertytypedescription") or ""
            propertyamount = property_details.get("propertyamount")
            ownerstate = property_details.get("ownerstate") or "Georgia"
        else:
            # PropertyView object
            reportyear = property_details.reportyear or ""
            holdername = property_details.holdername or ""
            propertytypedescription = property_details.propertytypedescription or ""
            propertyamount = property_details.propertyamount
            ownerstate = property_details.ownerstate or "Georgia"
        
        context.update({
            "YYYY": reportyear,
            "HolderName": holdername,
            "Holder Name": holdername,
            "Type": propertytypedescription,
            "Amount": _format_amount(propertyamount) if propertyamount else "",
            "Exact or Range": _format_amount(propertyamount) if propertyamount else "",
            "State": ownerstate,  # For LinkedIn templates
        })
    else:
        context.update({
            "YYYY": "",
            "HolderName": "",
            "Holder Name": "",
            "Type": "",
            "Amount": "",
            "Exact or Range": "",
            "State": "Georgia",  # Default fallback
        })
    
    return context


def _render_template(template_name: str, context: Dict[str, Any]) -> str:
    """Render email template with context using simple string replacement."""
    template_path = TEMPLATE_DIR / template_name
    if not template_path.exists():
        raise ValueError(f"Template {template_name} not found")
    
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Replace all placeholders in the format [PlaceholderName]
    for key, value in context.items():
        placeholder = f"[{key}]"
        content = content.replace(placeholder, str(value) if value else "")
    
    return content


def resolve_profile(profile_key: Optional[str]) -> Dict[str, str]:
    """Return profile configuration (with key) for the requested sender."""
    key = (profile_key or DEFAULT_PROFILE_KEY).lower()
    profile = PROFILE_REGISTRY.get(key, PROFILE_REGISTRY[DEFAULT_PROFILE_KEY])
    return {**profile, "key": key}


def embed_profile_marker(body: str, profile_key: str) -> str:
    """Embed profile marker at the beginning of the body for scheduled emails."""
    if not body:
        return f"{PROFILE_MARKER_PREFIX}{profile_key}{PROFILE_MARKER_SUFFIX}"
    
    clean_body = body
    if clean_body.startswith(PROFILE_MARKER_PREFIX):
        _, clean_body = extract_profile_marker(clean_body)
    
    return f"{PROFILE_MARKER_PREFIX}{profile_key}{PROFILE_MARKER_SUFFIX}{clean_body}"


def extract_profile_marker(body: str | None) -> tuple[str, str]:
    """Extract profile marker from stored email body."""
    if not body:
        return DEFAULT_PROFILE_KEY, ""
    
    if body.startswith(PROFILE_MARKER_PREFIX):
        marker_end = body.find(PROFILE_MARKER_SUFFIX)
        if marker_end != -1:
            profile_key = body[len(PROFILE_MARKER_PREFIX):marker_end].strip().lower()
            clean_body = body[marker_end + len(PROFILE_MARKER_SUFFIX):]
            if profile_key not in PROFILE_REGISTRY:
                profile_key = DEFAULT_PROFILE_KEY
            return profile_key, clean_body
    
    return DEFAULT_PROFILE_KEY, body


def _render_signature(signature_template: str, profile: Dict[str, str]) -> str:
    """Render email signature template with profile data."""
    template_path = TEMPLATE_DIR / signature_template
    if not template_path.exists():
        return ""
    
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Replace placeholders with profile data
    replacements = {
        "FullName": profile.get("full_name", ""),
        "Title": profile.get("title", ""),
        "Phone": profile.get("phone", ""),
        "Email": profile.get("from_email", ""),
    }
    
    for key, value in replacements.items():
        placeholder = f"[{key}]"
        content = content.replace(placeholder, str(value) if value else "")
    
    return content


def build_email_body(
    lead: BusinessLead,
    contact: LeadContact,
    property_details: Optional[PropertyView],
    profile_key: Optional[str] = None,
    template_variant: str = "initial",
) -> str:
    """
    Build complete email body by rendering template and appending signature.
    Returns empty string if no matching template found.
    
    Args:
        lead: The business lead
        contact: The contact to email
        property_details: Property details (optional)
        profile_key: Email profile key
        template_variant: One of "initial", "followup_1", "followup_2"
    """
    template_name = _get_template_name(lead, template_variant)
    if not template_name:
        return ""
    
    profile = resolve_profile(profile_key)
    context = _build_template_context(lead, contact, property_details, profile=profile)
    body_content = _render_template(template_name, context)
    signature = _render_signature(profile["signature_template"], profile)
    
    return f"{body_content}\n{signature}"


def build_email_subject(lead: BusinessLead, template_variant: str = "initial") -> str:
    """
    Build email subject line based on lead status and template variant.
    
    Args:
        lead: The business lead
        template_variant: One of "initial", "followup_1", "followup_2"
    """
    property_id = lead.property_id or ""
    
    # Subject templates organized by owner_type, business_owner_status, and template_variant
    SUBJECT_TEMPLATES = {
        OwnerType.individual: {
            "initial": "Unclaimed Property Reported Under Your Name (GA – Ref: {id})",
            "followup_1": "Follow-up: Unclaimed Property Under Your Name (GA – Ref: {id})",
            "followup_2": "Final Check: Unclaimed Property Under Your Name (GA – Ref: {id})",
        },
        OwnerType.business: {
            BusinessOwnerStatus.active: {
                "initial": "Unclaimed Property for {company} (GA – Ref: {id})",
                "followup_1": "Follow-up: Unclaimed Property for {company} (GA – Ref: {id})",
                "followup_2": "Final Check: Unclaimed Property for {company} (GA – Ref: {id})",
            },
            BusinessOwnerStatus.acquired_or_merged: {
                "initial": "Unclaimed Property Reported Under Former Entity: {company} (GA – Ref: {id})",
                "followup_1": "Follow-up: Unclaimed Property – Former Entity {company} (GA – Ref: {id})",
                "followup_2": "Final Check: Unclaimed Property – Former Entity {company} (GA – Ref: {id})",
            },
            BusinessOwnerStatus.active_renamed: {
                "initial": "Unclaimed Property Reported Under Former Entity: {company} (GA – Ref: {id})",
                "followup_1": "Follow-up: Unclaimed Property – Former Entity {company} (GA – Ref: {id})",
                "followup_2": "Final Check: Unclaimed Property – Former Entity {company} (GA – Ref: {id})",
            },
            BusinessOwnerStatus.dissolved: {
                "initial": "Unclaimed Property Reported Under Dissolved Business: {company} (GA – Ref: {id})",
                "followup_1": "",  # Empty for dissolved followup_1
                "followup_2": "Follow-up: Unclaimed Property – {company} (GA – Ref: {id})",
            },
        },
    }
    
    # Get template based on owner type
    if lead.owner_type == OwnerType.individual:
        template = SUBJECT_TEMPLATES[OwnerType.individual].get(template_variant)
        if template:
            return template.format(id=property_id)
        # Fallback to initial if variant not found
        return SUBJECT_TEMPLATES[OwnerType.individual]["initial"].format(id=property_id)
    
    # Business owner types
    if lead.owner_type == OwnerType.business and lead.business_owner_status:
        status_templates = SUBJECT_TEMPLATES[OwnerType.business].get(lead.business_owner_status)
        if status_templates:
            template = status_templates.get(template_variant)
            if template is not None:  # Check if key exists (even if empty string)
                # Use new_business_name for acquired/renamed if available, otherwise owner_name
                company_name = lead.owner_name
                if lead.business_owner_status in (BusinessOwnerStatus.acquired_or_merged, BusinessOwnerStatus.active_renamed):
                    company_name = lead.new_business_name or lead.owner_name
                elif lead.business_owner_status == BusinessOwnerStatus.dissolved:
                    company_name = lead.owner_name
                
                # Handle empty template (e.g., dissolved followup_1) - return empty string as specified
                if template.strip():
                    return template.format(company=company_name, id=property_id)
                else:
                    # Return empty string for intentionally empty templates
                    return ""
    
    # Fallback
    return f"Unclaimed Property Inquiry (GA – Ref: {property_id})"


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    reply_to: Optional[str] = None,
    smtp_username: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """
    Send email via SMTP with anti-spam best practices.
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_body: HTML email body
        from_email: Sender email (required)
        from_name: Sender name (required)
        reply_to: Reply-to address (required)
        smtp_username: SMTP login username (required - profile email)
        smtp_password: SMTP login password (required - profile password)
    
    Raises:
        ValueError: If SMTP credentials are missing
        smtplib.SMTPException: If email sending fails
    """
    # All parameters are required - no fallbacks
    if not from_email:
        raise ValueError("from_email is required")
    if not from_name:
        raise ValueError("from_name is required")
    if not reply_to:
        raise ValueError("reply_to is required")
    if not smtp_username:
        raise ValueError("smtp_username is required")
    if not smtp_password or smtp_password.strip() == "":
        raise ValueError(f"SMTP password is required for profile email {smtp_username}")
    
    smtp_user = smtp_username
    smtp_pass = smtp_password
    
    # Create message
    msg = MIMEMultipart("alternative")
    
    # Headers with anti-spam best practices
    msg["From"] = f"{Header(from_name, 'utf-8')} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = Header(subject, "utf-8")
    msg["Reply-To"] = reply_to
    msg["X-Mailer"] = "Load Router Lead Management System"
    msg["X-Priority"] = "3"  # Normal priority
    
    # Create plain text version (simple HTML strip)
    plain_body = html_body.replace("<strong>", "").replace("</strong>", "")
    plain_body = plain_body.replace("<p style=\"margin: 0 0 12px 0;\">", "").replace("</p>", "\n")
    plain_body = plain_body.replace("<div", "").replace("</div>", "")
    plain_body = plain_body.replace("<table", "").replace("</table>", "")
    plain_body = plain_body.replace("<tr", "").replace("</tr>", "")
    plain_body = plain_body.replace("<td", "").replace("</td>", "")
    plain_body = plain_body.replace("<ul", "").replace("</ul>", "")
    plain_body = plain_body.replace("<li", "").replace("</li>", "")
    plain_body = " ".join(plain_body.split())  # Normalize whitespace
    
    # Attach parts
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    
    # Send via SMTP
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()  # TLS encryption
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    except smtplib.SMTPException as e:
        raise Exception(f"Failed to send email: {str(e)}") from e


def prep_contact_email(
    db: Session,
    lead_id: int,
    contact_id: int,
    profile_key: Optional[str] = None,
    template_variant: str = "initial",
) -> Dict[str, Any]:
    """
    Prepare email content for a contact.
    Returns subject and body (empty if no template match).
    
    Args:
        db: Database session
        lead_id: Lead ID
        contact_id: Contact ID
        profile_key: Email profile key
        template_variant: One of "initial", "followup_1", "followup_2"
    """
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")
    
    contact = db.get(LeadContact, contact_id)
    if not contact:
        raise ValueError(f"Contact {contact_id} not found")
    
    if contact.lead_id != lead_id:
        raise ValueError("Contact does not belong to this lead")
    
    if not contact.email:
        raise ValueError("Contact has no email address")
    
    # Get property details - try raw_hash first, then property_id
    property_details = None
    if lead.property_raw_hash:
        from sqlalchemy import select
        property_details = db.scalar(
            select(PropertyView).where(PropertyView.raw_hash == lead.property_raw_hash)
        )
    
    # Fallback to property_id if raw_hash didn't work
    if not property_details and lead.property_id:
        from sqlalchemy import select
        property_details = db.scalar(
            select(PropertyView).where(PropertyView.propertyid == lead.property_id)
        )
    
    subject = build_email_subject(lead, template_variant=template_variant)
    body = build_email_body(lead, contact, property_details, profile_key=profile_key, template_variant=template_variant)
    profile = resolve_profile(profile_key)
    
    return {
        "to_email": contact.email,
        "to_name": contact.contact_name,
        "subject": subject,
        "body": body,
        "profile": profile["key"],
    }

