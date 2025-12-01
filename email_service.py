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


# SMTP Configuration (IONIO)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.ionos.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "fisseha@loadrouter.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "wAcheb-retqu4-dejriw")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "fisseha@loadrouter.com")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Fisseha Gebresilasie")
SMTP_REPLY_TO = os.getenv("SMTP_REPLY_TO", "fisseha@loadrouter.com")

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates" / "email"
SIGNATURE_TEMPLATE = "fisseha_signature.html"

# Template mapping based on lead status
TEMPLATE_MAP = {
    BusinessOwnerStatus.dissolved: "dissolved_inactive.html",
    BusinessOwnerStatus.acquired_or_merged: "acquired_merged.html",
    BusinessOwnerStatus.active_renamed: "acquired_merged.html",  # Use acquired template for renamed
    BusinessOwnerStatus.active: "active_company.html",
    OwnerType.individual: "Individual.html",
}


def _get_template_name(lead: BusinessLead) -> Optional[str]:
    """Determine which email template to use based on lead status."""
    if lead.owner_type == OwnerType.individual:
        return TEMPLATE_MAP[OwnerType.individual]
    
    if lead.owner_type == OwnerType.business and lead.business_owner_status:
        return TEMPLATE_MAP.get(lead.business_owner_status)
    
    return None


def _extract_first_name(contact_name: str) -> str:
    """Extract first name from contact name (first word)."""
    if not contact_name:
        return ""
    return contact_name.split()[0] if contact_name.split() else ""


def _format_amount(amount: Optional[Decimal]) -> str:
    """Format property amount for display."""
    if amount is None:
        return "—"
    return f"${amount:,.2f}"


def _build_template_context(
    lead: BusinessLead,
    contact: LeadContact,
    property_details: Optional[PropertyView],
) -> Dict[str, Any]:
    """Build context dictionary for template placeholder substitution."""
    context = {
        "FirstName": _extract_first_name(contact.contact_name),
        "ID": lead.property_id,
        "Company Legal Name": lead.owner_name,
        "Old Entity Legal Name": lead.owner_name,
        "OldBusinessName": lead.owner_name,
        "New Entity Name": lead.new_business_name or "",
    }
    
    if property_details:
        context.update({
            "YYYY": property_details.reportyear or "",
            "HolderName": property_details.holdername or "",
            "Holder Name": property_details.holdername or "",
            "Type": property_details.propertytypedescription or "",
            "Amount": _format_amount(property_details.propertyamount),
            "Exact or Range": _format_amount(property_details.propertyamount),
        })
    else:
        context.update({
            "YYYY": "",
            "HolderName": "",
            "Holder Name": "",
            "Type": "",
            "Amount": "",
            "Exact or Range": "",
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


def _render_signature() -> str:
    """Render email signature template."""
    template_path = TEMPLATE_DIR / SIGNATURE_TEMPLATE
    if not template_path.exists():
        return ""
    
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


def build_email_body(lead: BusinessLead, contact: LeadContact, property_details: Optional[PropertyView]) -> str:
    """
    Build complete email body by rendering template and appending signature.
    Returns empty string if no matching template found.
    """
    template_name = _get_template_name(lead)
    if not template_name:
        return ""
    
    context = _build_template_context(lead, contact, property_details)
    body_content = _render_template(template_name, context)
    signature = _render_signature()
    
    return f"{body_content}\n{signature}"


def build_email_subject(lead: BusinessLead) -> str:
    """Build email subject line based on lead status."""
    property_id = lead.property_id or ""
    
    if lead.owner_type == OwnerType.individual:
        return f"Unclaimed Property Reported Under Your Name (Georgia)"
    
    if lead.owner_type == OwnerType.business:
        if lead.business_owner_status == BusinessOwnerStatus.dissolved:
            return f"Unclaimed Property Reported Under Dissolved Business: {lead.owner_name} (GA – Ref: {property_id})"
        elif lead.business_owner_status == BusinessOwnerStatus.acquired_or_merged:
            return f"Unclaimed Property Reported Under Former Entity: {lead.owner_name} (GA – Ref: {property_id})"
        elif lead.business_owner_status == BusinessOwnerStatus.active_renamed:
            return f"Unclaimed Property Reported Under Former Entity: {lead.owner_name} (GA – Ref: {property_id})"
        elif lead.business_owner_status == BusinessOwnerStatus.active:
            return f"Unclaimed Property for {lead.owner_name} (GA – Ref: {property_id})"
    
    # Fallback
    return f"Unclaimed Property Inquiry (GA – Ref: {property_id})"


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    """
    Send email via SMTP with anti-spam best practices.
    
    Raises:
        ValueError: If SMTP credentials are missing
        smtplib.SMTPException: If email sending fails
    """
    if not SMTP_PASSWORD:
        raise ValueError("SMTP_PASSWORD environment variable is not set")
    
    from_email = from_email or SMTP_FROM_EMAIL
    from_name = from_name or SMTP_FROM_NAME
    reply_to = reply_to or SMTP_REPLY_TO
    
    # Create message
    msg = MIMEMultipart("alternative")
    
    # Headers with anti-spam best practices
    msg["From"] = f"{Header(from_name, 'utf-8')} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = Header(subject, "utf-8")
    msg["Reply-To"] = reply_to
    msg["X-Mailer"] = "LoadRouter Lead Management System"
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
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
    except smtplib.SMTPException as e:
        raise Exception(f"Failed to send email: {str(e)}") from e


def prep_contact_email(
    db: Session,
    lead_id: int,
    contact_id: int,
) -> Dict[str, Any]:
    """
    Prepare email content for a contact.
    Returns subject and body (empty if no template match).
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
    
    subject = build_email_subject(lead)
    body = build_email_body(lead, contact, property_details)
    
    return {
        "to_email": contact.email,
        "to_name": contact.contact_name,
        "subject": subject,
        "body": body,
    }

