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
)
from utils.name_utils import normalize_name, split_name, format_first_name


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
BASE_DIR = Path(__file__).resolve().parent
STATIC_ASSETS_DIR = BASE_DIR / "static"
IMG_ASSETS_DIR = STATIC_ASSETS_DIR / "img"

LOGO_PATH = (IMG_ASSETS_DIR / "favicon.ico").resolve()
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
    formatted_owner_name = normalize_name(original_owner_name)
    owner_first_name = format_first_name(original_owner_name)

    if lead.owner_type == OwnerType.business:
        company_for_body = original_owner_name
    else:
        company_for_body = ""

    primary_reference = getattr(property_details, "propertyid", "") or lead.property_id
    primary_holder = getattr(property_details, "holdername", "")
    primary_amount = getattr(property_details, "propertyamount", "") or lead.property_amount
    primary_year = getattr(property_details, "reportyear", "")
    primary_type = (
        getattr(property_details, "propertytypedescription", None)
        or getattr(property_details, "propertytype", None)
        or ""
    )

    total_properties = 1
    fee_percent = "10"

    recipient_display_name = formatted_contact_name or formatted_owner_name or (lead.owner_name or "").strip()
    salutation_name = raw_first_name or owner_first_name or "Sir or Madam"

    context = {
        "today": date.today().strftime("%B %d, %Y"),
        "recipient_name": recipient_display_name,
        "title": (contact.title or "").upper() or None,
        "company_name": company_for_body.upper() if company_for_body else None,
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
        "acquiring_company": new_owner_name,
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
    if not lead.property_raw_hash:
        return None
    return db.scalar(
        select(PropertyView).where(PropertyView.raw_hash == lead.property_raw_hash)
    )

