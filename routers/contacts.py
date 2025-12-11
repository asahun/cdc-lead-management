"""
Contact routes - handles contact management for leads.
"""

from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from db import get_db
from models import (
    BusinessLead,
    LeadContact,
    LeadStatus,
    ContactType,
    PrintLog,
    LeadJourney,
)
from services.property_service import get_property_by_id, get_property_details_for_lead
from services.journey_service import initialize_lead_journey
from utils import get_lead_or_404, get_contact_or_404
from services.letter_service import LetterGenerationError, get_property_for_lead, render_letter_pdf
from fastapi.templating import Jinja2Templates

# Import shared templates from main to ensure filters are registered
templates = None  # Will be set by main.py

router = APIRouter()


@router.get("/leads/{lead_id}/contacts", response_class=HTMLResponse)
def lead_contacts(
    request: Request,
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return RedirectResponse(
        url=f"/leads/{lead.id}/edit#contacts",
        status_code=302,
    )


@router.post("/leads/{lead_id}/contacts/create")
def create_lead_contact(
    lead_id: int,
    contact_name: str = Form(...),
    title: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    linkedin_url: str | None = Form(None),
    address_street: str | None = Form(None),
    address_city: str | None = Form(None),
    address_state: str | None = Form(None),
    address_zipcode: str | None = Form(None),
    contact_type: ContactType = Form(ContactType.employee),
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)

    contact = LeadContact(
        lead_id=lead.id,
        contact_name=contact_name,
        title=title,
        email=email,
        phone=phone,
        linkedin_url=linkedin_url,
        address_street=address_street,
        address_city=address_city,
        address_state=address_state or "GA",
        address_zipcode=address_zipcode,
        contact_type=contact_type,
    )
    db.add(contact)
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit#contacts", status_code=303)


@router.post("/leads/{lead_id}/contacts/{contact_id}/delete")
def delete_lead_contact(
    lead_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")

    db.delete(contact)
    db.commit()
    return RedirectResponse(url=f"/leads/{lead_id}/edit#contacts", status_code=303)


@router.post("/leads/{lead_id}/contacts/{contact_id}/update")
def update_lead_contact(
    lead_id: int,
    contact_id: int,
    contact_name: str = Form(...),
    title: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    linkedin_url: str | None = Form(None),
    address_street: str | None = Form(None),
    address_city: str | None = Form(None),
    address_state: str | None = Form(None),
    address_zipcode: str | None = Form(None),
    contact_type: ContactType = Form(ContactType.employee),
    db: Session = Depends(get_db),
):
    contact = get_contact_or_404(db, contact_id, lead_id)

    contact.contact_name = contact_name
    contact.title = title
    contact.email = email
    contact.phone = phone
    contact.linkedin_url = linkedin_url
    contact.address_street = address_street
    contact.address_city = address_city
    contact.address_state = address_state or "GA"
    contact.address_zipcode = address_zipcode
    contact.contact_type = contact_type
    contact.updated_at = datetime.now(timezone.utc)

    db.commit()
    return RedirectResponse(url=f"/leads/{lead_id}/edit#contacts", status_code=303)


@router.post("/leads/{lead_id}/contacts/{contact_id}/mark-primary")
def mark_contact_as_primary(
    lead_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    """Mark a contact as primary and initialize/update journey."""
    lead = get_lead_or_404(db, lead_id)
    contact = get_contact_or_404(db, contact_id, lead_id)
    
    if lead.status in {LeadStatus.new, LeadStatus.researching, LeadStatus.invalid, LeadStatus.competitor_claimed}:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot mark contact as primary. Lead must be in 'ready' status or later. Current status: {lead.status.value}"
        )
    
    db.query(LeadContact).filter(
        LeadContact.lead_id == lead_id,
        LeadContact.id != contact_id,
        LeadContact.is_primary == True
    ).update({"is_primary": False})
    
    contact.is_primary = True
    contact.updated_at = datetime.now(timezone.utc)
    db.flush()
    
    journey = initialize_lead_journey(db, lead_id, primary_contact_id=contact_id)
    if not journey:
        db.rollback()
        raise HTTPException(status_code=400, detail="Failed to initialize journey")
    
    db.commit()
    
    return RedirectResponse(url=f"/leads/{lead_id}/edit#contacts", status_code=303)


@router.post("/leads/{lead_id}/contacts/{contact_id}/letters")
def generate_contact_letter(
    lead_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")

    address_fields = [
        contact.address_street,
        contact.address_city,
        contact.address_state,
        contact.address_zipcode,
    ]
    if not all(address_fields):
        raise HTTPException(
            status_code=400,
            detail="Contact must have street, city, state, and ZIP before generating a letter.",
        )

    property_details = get_property_for_lead(db, lead)
    if not property_details:
        property_details = get_property_by_id(db, lead.property_id)

    if not property_details:
        raise HTTPException(
            status_code=400,
            detail="Lead is not associated with a property record.",
        )

    try:
        pdf_bytes, filename = render_letter_pdf(
            templates.env, lead, contact, property_details
        )
    except LetterGenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    display_path = f"Downloads/{filename}"
    print_log = PrintLog(
        lead_id=lead.id,
        contact_id=contact.id,
        filename=filename,
        file_path=display_path,
    )
    db.add(print_log)
    db.commit()

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)


@router.get("/leads/{lead_id}/contacts/{contact_id}/prep-email")
def prep_email(
    lead_id: int,
    contact_id: int,
    profile: str | None = Query(None),
    template_variant: str = Query("initial", description="Template variant: initial, followup_1, followup_2"),
    db: Session = Depends(get_db),
):
    """Prepare email content for a contact."""
    from services.email_service import prep_contact_email
    
    if template_variant not in ("initial", "followup_1", "followup_2"):
        raise HTTPException(status_code=400, detail="Invalid template_variant. Must be one of: initial, followup_1, followup_2")
    
    try:
        email_data = prep_contact_email(db, lead_id, contact_id, profile_key=profile, template_variant=template_variant)
        from fastapi.responses import JSONResponse
        return JSONResponse(content=email_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

