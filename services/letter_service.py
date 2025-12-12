from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional, Tuple
import tempfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    BusinessLead,
    BusinessOwnerStatus,
    LeadContact,
    OwnerType,
    PropertyView,
    ContactType,
)
from utils.name_utils import normalize_name, split_name, format_first_name
from utils import format_currency
from services.property_service import get_property_by_id
from services.email_service import resolve_profile, DEFAULT_PROFILE_KEY


class LetterGenerationError(Exception):
    """Raised when a letter cannot be generated."""


TEMPLATE_MAP = {
    "individual": "letters/individual.html",
    "active_business": "letters/active_business.html",
    "acquired_merged": "letters/acquired_merged.html",
    "dissolved_no_owner": "letters/dissolved_no_owner.html",
}

FILENAME_PREFIX = {
    "individual": "individual_",
    "acquired_merged": "acquired_",
    "active_business": "active_",
    "dissolved_no_owner": "dissolved_",
}

# Paths for shared assets (logos, QR, signature)
# Go up one level from services/ to root
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_ASSETS_DIR = BASE_DIR / "static"
IMG_ASSETS_DIR = STATIC_ASSETS_DIR / "img"

LOGO_PATH = (IMG_ASSETS_DIR / "logo.png").resolve()
QR_PATH = (IMG_ASSETS_DIR / "qr.png").resolve()
SIGNATURE_PATH = (IMG_ASSETS_DIR / "signature_fish.png").resolve()


def _determine_template_key(lead: BusinessLead) -> str:
    if lead.owner_type == OwnerType.individual:
        return "individual"

    status = lead.business_owner_status or BusinessOwnerStatus.active
    if status in (BusinessOwnerStatus.acquired_or_merged, BusinessOwnerStatus.active_renamed):
        return "acquired_merged"
    if status == BusinessOwnerStatus.dissolved:
        return "dissolved_no_owner"
    return "active_business"


def _build_address_lines(contact: LeadContact) -> Tuple[str, str]:
    street = (contact.address_street or "").strip().upper()
    city = (contact.address_city or "").strip().upper()
    state = (contact.address_state or "").strip().upper()
    zipcode = (contact.address_zipcode or "").strip().upper()

    parts = [part for part in (city, state) if part]
    city_state = ", ".join(parts)
    city_state_zip = " ".join(part for part in (city_state, zipcode) if part)
    return street, city_state_zip


def render_letter_pdf(
    jinja_env,
    lead: BusinessLead,
    contact: LeadContact,
    property_details: Optional[PropertyView],
) -> Tuple[bytes, str]:
    template_key = _determine_template_key(lead)
    template_path = TEMPLATE_MAP.get(template_key)
    if not template_path:
        raise LetterGenerationError(f"No template configured for key '{template_key}'")

    try:
        template = jinja_env.get_template(template_path)
    except Exception as exc:  # pragma: no cover
        raise LetterGenerationError(f"Unable to load template '{template_path}': {exc}") from exc

    contact_name = (contact.contact_name or "").strip()
    formatted_contact_name = normalize_name(contact_name)
    raw_first_name, raw_last_name = split_name(contact_name)

    street, city_state_zip = _build_address_lines(contact)

    new_owner_name = (lead.new_business_name or "").strip()
    original_owner_name = (lead.owner_name or "").strip()
    business_name_for_address = new_owner_name or original_owner_name
    formatted_owner_name = normalize_name(original_owner_name)
    owner_first_name = format_first_name(original_owner_name)

    # Always use the current business name for company references (new name if present, else owner_name)
    company_for_body = business_name_for_address

    # Get primary property
    from helpers.property_helpers import get_primary_property
    primary_prop = get_primary_property(lead)
    
    primary_reference = getattr(property_details, "propertyid", "") or (primary_prop.property_id if primary_prop else "")
    primary_holder = getattr(property_details, "holdername", "")
    primary_amount = getattr(property_details, "propertyamount", "") or (primary_prop.property_amount if primary_prop else None)
    primary_year = getattr(property_details, "reportyear", "")
    primary_type = (
        getattr(property_details, "propertytypedescription", None)
        or getattr(property_details, "propertytype", None)
        or ""
    )

    total_properties = 1
    fee_percent = "10"

    # Determine recipient/salutation rules
    ct = contact.contact_type
    is_agent_company = (
        ct == ContactType.agent_company
        or getattr(ct, "value", None) == "agent_company"
        or str(ct).split(".")[-1] == "agent_company"
    )
    business_recipient = business_name_for_address or (formatted_owner_name or (lead.owner_name or "").strip())
    company_name_for_body = company_for_body.upper() if company_for_body else None
    company_name_for_address = company_name_for_body
    c_o_name = contact_name if is_agent_company else None
    acquiring_company_for_template = new_owner_name

    if is_agent_company:
        # No person; recipient is the business; add C/O agent company; no title
        recipient_display_name = business_recipient
        salutation_name = "To Whom It May Concern,"
        title_for_address = None
        # Show business line in address; agent shown as C/O in template
        company_name_for_address = company_name_for_body
        acquiring_company_for_template = None
    elif contact_name:
        # Person contact: use person as recipient, include title, include company line
        recipient_display_name = formatted_contact_name
        salutation_name = raw_first_name or owner_first_name or "Sir or Madam"
        title_for_address = (contact.title or "").upper() or None
        company_name_for_address = company_name_for_body
    else:
        # Fallback: use business as recipient, no title, include company line
        recipient_display_name = business_recipient
        salutation_name = owner_first_name or "Sir or Madam"
        title_for_address = None
        company_name_for_address = company_name_for_body

    context = {
        "today": date.today().strftime("%B %d, %Y"),
        "recipient_name": recipient_display_name,
        "title": title_for_address,
        "company_name": company_name_for_address,
        "company_name_body": company_name_for_body,
        "c_o_name": c_o_name,
        "street_address": street,
        "city_state_zip": city_state_zip,
        "subject_name": formatted_owner_name or formatted_contact_name or "you",
        "salutation": salutation_name,
        "raw_first_name": raw_first_name,
        "raw_last_name": raw_last_name,
        "raw_company_name": company_for_body,
        "template_key": template_key,
        "primary_reference": primary_reference,
        "primary_holder": primary_holder,
        "primary_amount": primary_amount,
        "primary_year": primary_year,
        "primary_type": primary_type,
        "total_properties": total_properties,
        "acquiring_company": acquiring_company_for_template,
        "fee_percent": fee_percent,
        "sender_first_name": "Fisseha",
        "sender_last_name": "Gebresilasie",
        "sender_title": "Client Relations & Compliance Manager",
        "sender_company": "Load Router, LLC",
        "sender_subtitle": "Business & Personal Unclaimed Property Recovery",
        "sender_addr_line1": "4575 Webb Bridge Rd #2311",
        "sender_addr_line2": "Alpharetta, GA 30005",
        "sender_phone": "(404) 654-3593",
        "sender_email": "fisseha@loadrouter.com",
        "sender_website": "www.loadrouter.com",
        "logo_src": LOGO_PATH.as_uri() if LOGO_PATH.exists() else "",
        "qr_src": QR_PATH.as_uri() if QR_PATH.exists() else "",
        "signature_src": SIGNATURE_PATH.as_uri() if SIGNATURE_PATH.exists() else "",
    }

    html = template.render(**context)
    pdf_bytes = _render_pdf_from_html(html)

    slug_source = original_owner_name or contact_name or lead.owner_name or "letter"
    slug_base = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in slug_source.strip().lower()).strip("_") or "letter"
    prefix = FILENAME_PREFIX.get(template_key, "")
    filename = f"{prefix}{slug_base}.pdf"

    return pdf_bytes, filename


def render_one_pager_pdf(
    jinja_env,
    lead: BusinessLead,
    property_details: Optional[PropertyView],
    db: Session,
) -> Tuple[bytes, str]:
    """
    Render a one-pager PDF for a lead (no contact info).
    """
    template_path = "one_pagers/business_one_pager.html"

    try:
        template = jinja_env.get_template(template_path)
    except Exception as exc:  # pragma: no cover
        raise LetterGenerationError(f"Unable to load template '{template_path}': {exc}") from exc

    from helpers.property_helpers import get_primary_property

    primary_prop = get_primary_property(lead)

    new_owner_name = (lead.new_business_name or "").strip()
    owner_name = (lead.owner_name or "").strip()
    company_legal_name = new_owner_name or owner_name

    # Scenario mapping
    if lead.business_owner_status == BusinessOwnerStatus.dissolved:
        scenario = "dissolved"
    elif lead.business_owner_status in (BusinessOwnerStatus.acquired_or_merged, BusinessOwnerStatus.active_renamed):
        scenario = "former_entity"
    else:
        scenario = "active"

    old_entity_name = owner_name if scenario == "former_entity" and owner_name else None

    report_year = getattr(property_details, "reportyear", "") if property_details else ""
    holder_name = getattr(property_details, "holdername", "") if property_details else ""
    property_type = (
        getattr(property_details, "propertytypedescription", None)
        or getattr(property_details, "propertytype", None)
        or ""
    ) if property_details else ""

    amount_val = None
    if property_details and getattr(property_details, "propertyamount", None) not in (None, ""):
        amount_val = property_details.propertyamount
    elif primary_prop and getattr(primary_prop, "property_amount", None) not in (None, ""):
        amount_val = primary_prop.property_amount
    amount = format_currency(amount_val) if amount_val not in (None, "") else "—"

    state_ref = getattr(property_details, "propertyid", "") if property_details else ""
    if not state_ref and primary_prop:
        state_ref = primary_prop.property_id or ""

    state_portal_url = "https://gaclaims.unclaimedproperty.com/"
    today_str = date.today().strftime("%B %d, %Y")

    # Logo and sender info (use default profile for consistency)
    logo_path = LOGO_PATH.as_uri() if LOGO_PATH.exists() else ""
    profile = resolve_profile(DEFAULT_PROFILE_KEY)
    sender_name = "Load Router, LLC"
    sender_team = profile.get("full_name", profile.get("label", "Client Relations"))
    sender_phone = profile.get("phone", "")
    sender_email = profile.get("from_email", "")
    sender_website = "www.loadrouter.com"

    # Lead address info (for Known Address)
    lead_address = ", ".join(
        part for part in [
            getattr(lead, "owner_address", None),
            getattr(lead, "owner_city", None),
            getattr(lead, "owner_state", None),
            getattr(lead, "owner_zipcode", None),
        ] if part
    ) or "—"

    # Primary contact status (for display)
    primary_contact = next((c for c in lead.contacts if getattr(c, "is_primary", False)), None) if hasattr(lead, "contacts") else None
    if primary_contact:
        primary_contact_status = primary_contact.contact_name
    else:
        primary_contact_status = "Not yet designated"

    # Build record list from lead.properties; fallback to primary property_details if none
    records = []
    for prop in getattr(lead, "properties", []) or []:
        pd = get_property_by_id(db, prop.property_id) if prop.property_id else None
        # pd may be a dict; handle both dict and object
        def _get(obj, key):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        ref = _get(pd, "propertyid") or getattr(prop, "property_id", "") or ""
        holder = _get(pd, "holdername") or getattr(prop, "holder_name", None)
        ptype = (
            _get(pd, "propertytypedescription")
            or _get(pd, "propertytype")
            or ""
        )
        amt_val = _get(pd, "propertyamount")
        if amt_val in (None, ""):
            amt_val = getattr(prop, "property_amount", None)
        amt_fmt = format_currency(amt_val) if amt_val not in (None, "") else "—"
        records.append({
            "ref": ref or "—",
            "holder": holder or "—",
            "ptype": ptype or "—",
            "amount": amt_fmt,
        })

    # If no records collected but property_details exists, add primary
    if not records and property_details:
        def _get_pd(obj, key):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        ref = _get_pd(property_details, "propertyid") or "—"
        holder = _get_pd(property_details, "holdername") or "—"
        ptype = (
            _get_pd(property_details, "propertytypedescription")
            or _get_pd(property_details, "propertytype")
            or "—"
        )
        amt_val = _get_pd(property_details, "propertyamount")
        amt_fmt = format_currency(amt_val) if amt_val not in (None, "") else "—"
        records.append({
            "ref": ref,
            "holder": holder,
            "ptype": ptype,
            "amount": amt_fmt,
        })

    has_more_than_5 = len(records) > 5
    records_display = records[:5] if has_more_than_5 else records

    context = {
        "date": today_str,
        "state_ref": state_ref,
        "company_legal_name": company_legal_name,
        "scenario": scenario,
        "old_entity_name": old_entity_name,
        "report_year": report_year,
        "holder_name": holder_name,
        "property_type": property_type,
        "amount": amount,
        "state_portal_url": state_portal_url,
        "has_more_than_5": has_more_than_5,
        "records": records_display,
        # Sender/branding
        "LogoUrlOrPath": logo_path,
        "YourBusinessName": sender_name,
        "YourNameOrTeam": sender_team,
        "YourPhone": sender_phone,
        "YourEmail": sender_email,
        "YourWebsite": sender_website,
        # Prepared for
        "CompanyName": company_legal_name,
        "TodayDate": today_str,
        "FEINorBlank": "—",
        "KnownAddress": lead_address,
        "PrimaryContactStatus": primary_contact_status,
    }

    html = template.render(**context)
    pdf_bytes = _render_pdf_from_html(html)

    def _slugify(val) -> str:
        # Accept non-string (e.g., Decimal), convert safely
        text = str(val or "").strip()
        safe = "".join(ch if ch.isalnum() else "_" for ch in text)
        return safe.strip("_") or "one_pager"

    company_slug = _slugify(company_legal_name)
    ref_slug = _slugify(state_ref) if state_ref else "ref"
    filename = f"Unclaimed_Property_Summary_{company_slug}_{ref_slug}.pdf"

    return pdf_bytes, filename


def _render_pdf_from_html(html: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="cdr_letter_") as tmp_dir:
        tmp_html_path = Path(tmp_dir) / "letter.html"
        tmp_html_path.write_text(html, encoding="utf-8")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise LetterGenerationError(
                "Playwright is required to generate PDFs. Install it with 'pip install playwright' "
                "and run 'playwright install chromium'."
            ) from exc

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(tmp_html_path.as_uri(), wait_until="networkidle")
            pdf_bytes = page.pdf(
                print_background=True,
                format="Letter",
                prefer_css_page_size=False,
                margin={
                    "top": "0.3in",
                    "right": "0.3in",
                    "bottom": "0.3in",
                    "left": "0.3in",
                },
            )
            browser.close()
    return pdf_bytes


def get_property_for_lead(db: Session, lead: BusinessLead) -> Optional[PropertyView]:
    from helpers.property_helpers import get_primary_property
    primary_prop = get_primary_property(lead)
    if not primary_prop or not primary_prop.property_raw_hash:
        return None
    return db.scalar(
        select(PropertyView).where(PropertyView.raw_hash == primary_prop.property_raw_hash)
    )

