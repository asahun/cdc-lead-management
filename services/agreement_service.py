import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from models import (
    Lead, LeadContact, LeadProperty, LeadStatus,
    Claim, ClaimEvent, ClaimDocument,
    Client, ClientContact, ClientMailingAddress, SignerType
)
from scripts.fill_recovery_agreement import build_field_mapping as build_recovery_mapping
from scripts.fill_recover_authorization_letter import build_field_mapping as build_auth_mapping
from scripts.pdf_fill_reportlab import fill_pdf_fields_reportlab
import json


TEMPLATES_DIR = Path("scripts/pdf_templates")
OUTPUT_ROOT = Path("scripts/pdf_output")
CDR_PROFILE_PATH = Path("scripts/data/cdr_profile.json")

# Claim status events (exclude file-related states)
CLAIM_STATUS_STATES = [
    "claim_created",
    "agreement_generated",
    "agreement_sent",
    "agreement_signed",
    "claim_preparing",
    "claim_submitted",
    "pending",
    "approved",
    "rejected",
    "more_info",
]


def _format_amount(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except Exception:
        try:
            return f"{float(str(value).replace(',', '')):,.2f}"
        except Exception:
            return ""


def _load_cdr_profile() -> Dict[str, Any]:
    if not CDR_PROFILE_PATH.exists():
        raise FileNotFoundError(f"CDR profile file not found: {CDR_PROFILE_PATH}")
    return json.loads(CDR_PROFILE_PATH.read_text())


def _get_or_create_client(
    db: Session,
    lead: Lead,
    control_no: str,
    formation_state: str,
    entitled_business_name: str,
) -> Client:
    """Get or create a client. For now, we create a new client for each claim.
    In the future, we can add logic to find existing clients by business name."""
    # Create new client (can be enhanced later to find existing clients)
    client = Client(
        entitled_business_name=entitled_business_name,
        formation_state=formation_state,
        control_no=control_no,
    )
    db.add(client)
    db.flush()
    return client


def _copy_contact_to_client(
    db: Session,
    client: Client,
    lead_contact: LeadContact,
    signer_type: SignerType,
) -> ClientContact:
    """Copy lead contact to client contact."""
    # Split contact name into first and last name
    name_parts = (lead_contact.contact_name or "").strip().split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    
    client_contact = ClientContact(
        client_id=client.id,
        lead_contact_id=lead_contact.id,
        signer_type=signer_type,
        first_name=first_name,
        last_name=last_name,
        title=lead_contact.title,
        email=lead_contact.email,
        phone=lead_contact.phone,
    )
    db.add(client_contact)
    return client_contact


def _copy_address_to_client(
    db: Session,
    client: Client,
    lead_contact: LeadContact,
) -> ClientMailingAddress:
    """Copy lead contact address to client mailing address."""
    client_address = ClientMailingAddress(
        client_id=client.id,
        street=lead_contact.address_street or "",
        line2=None,
        city=lead_contact.address_city or "",
        state=lead_contact.address_state or "",
        zip=lead_contact.address_zipcode or "",
    )
    db.add(client_address)
    return client_address


def _ensure_claim(
    db: Session,
    lead: Lead,
    control_no: str,
    formation_state: str,
    fee_pct: str,
    addendum_yes: bool,
    primary_contact: LeadContact,
    cdr_profile: Dict[str, Any],
    entitled_business_name: str = None,
    entitled_business_same_as_owner: bool = True,
) -> Claim:
    """Create or update claim with new client structure."""
    existing = (
        db.query(Claim)
        .filter(Claim.lead_id == lead.id)
        .order_by(Claim.id.desc())
        .first()
    )
    
    if existing:
        claim = existing
        # Update client if needed
        if claim.client:
            if formation_state:
                claim.client.formation_state = formation_state
            if control_no:
                claim.client.control_no = control_no
        # Update claim fields
        if fee_pct:
            claim.fee_pct = float(fee_pct)
            claim.fee_flat = None
        claim.addendum_yes = bool(addendum_yes)
    else:
        # Create new client
        business_name = entitled_business_name if entitled_business_name else lead.owner_name
        client = _get_or_create_client(
            db=db,
            lead=lead,
            control_no=control_no,
            formation_state=formation_state,
            entitled_business_name=business_name,
        )
        db.flush()
        
        # Copy primary contact to client
        primary_client_contact = _copy_contact_to_client(
            db=db,
            client=client,
            lead_contact=primary_contact,
            signer_type=SignerType.primary,
        )
        db.flush()
        
        # Copy address to client
        client_address = _copy_address_to_client(
            db=db,
            client=client,
            lead_contact=primary_contact,
        )
        db.flush()
        
        # Calculate fee
        fee_pct_val = float(fee_pct) if fee_pct else 10.0
        
        # Create claim
        claim = Claim(
            client_id=client.id,
            lead_id=lead.id,
            claim_slug=f"claim-{lead.id}-{int(datetime.utcnow().timestamp())}",
            entitled_business_name=business_name,
            entitled_business_same_as_owner=entitled_business_same_as_owner,
            fee_pct=fee_pct_val,
            fee_flat=None,
            cdr_fee=None,  # Will be calculated later
            addendum_yes=bool(addendum_yes),
            check_mailing_address_id=client_address.id,
            output_dir=None,
        )
        db.add(claim)
        db.flush()
    
    return claim


def create_claim_from_lead(
    db: Session,
    lead_id: int,
    control_no: str,
    formation_state: str,
    fee_pct: str,
    addendum_yes: bool,
    user: str = None,
    entitled_business_name: str = None,
    entitled_business_same_as_owner: bool = True,
) -> Dict[str, Any]:
    lead = db.query(Lead).filter(Lead.id == lead_id).one_or_none()
    if not lead:
        raise ValueError("Lead not found")

    primary_contact = _get_primary_contact(lead)
    if not primary_contact:
        raise ValueError("No primary contact found")
    required_contact_fields = [
        primary_contact.email,
        primary_contact.phone,
        primary_contact.address_street,
        primary_contact.address_city,
        primary_contact.address_state,
        primary_contact.address_zipcode,
    ]
    if not all(required_contact_fields):
        raise ValueError("Primary contact must have email, phone, and full address")

    cdr_profile = _load_cdr_profile()
    business_name = entitled_business_name if entitled_business_name else lead.owner_name
    claim = _ensure_claim(
        db,
        lead,
        control_no,
        formation_state,
        fee_pct,
        addendum_yes,
        primary_contact,
        cdr_profile,
        entitled_business_name=business_name,
        entitled_business_same_as_owner=entitled_business_same_as_owner,
    )
    db.flush()

    if not claim.output_dir:
        claim.output_dir = str(OUTPUT_ROOT / f"claim-{claim.id}")
    Path(claim.output_dir).mkdir(parents=True, exist_ok=True)

    # Record claim_created event
    event_payload = {
        "claim_id": claim.id,
        "claim_slug": claim.claim_slug,
        "control_no": control_no,
        "formation_state": formation_state,
        "fee_pct": fee_pct,
        "addendum_yes": addendum_yes,
    }
    _record_event(db, claim, "claim_created", event_payload, user=user)
    db.commit()

    return {
        "claim_id": claim.id,
        "claim_slug": claim.claim_slug,
        "output_dir": claim.output_dir,
    }


def _record_event(db: Session, claim: Claim, state: str, payload: Dict[str, Any], user: str = None) -> ClaimEvent:
    payload_json = json.dumps(payload)
    event = ClaimEvent(
        claim_id=claim.id,
        state=state,
        payload=payload_json,
        created_by=user,
        created_at=datetime.utcnow(),
    )
    db.add(event)
    return event


def _get_primary_contact(lead: Lead) -> LeadContact:
    for c in lead.contacts:
        if c.is_primary:
            return c
    return lead.contacts[0] if lead.contacts else None


def generate_agreements(
    db: Session,
    lead_id: int,
    control_no: str,
    formation_state: str,
    fee_pct: str,
    addendum_yes: bool,
    user: str = None,
) -> Dict[str, Any]:
    latest = get_latest_claim_summary(db, lead_id)
    if not latest:
        raise ValueError("No claim found for lead")
    return generate_agreements_for_claim(
        db=db,
        claim_id=latest["id"],
        control_no=control_no,
        formation_state=formation_state,
        fee_pct=fee_pct,
        addendum_yes=addendum_yes,
        user=user,
    )


def generate_agreements_for_claim(
    db: Session,
    claim_id: int,
    control_no: str,
    formation_state: str,
    fee_pct: str,
    addendum_yes: bool,
    user: str = None,
    fee_flat: str = None,
) -> Dict[str, Any]:
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise ValueError("Claim not found")
    lead = claim.lead
    if not lead:
        raise ValueError("Lead not found for claim")
    client = claim.client
    if not client:
        raise ValueError("Client not found for claim")

    # Get primary signer contact from client
    primary_client_contact = (
        db.query(ClientContact)
        .filter(ClientContact.client_id == client.id, ClientContact.signer_type == SignerType.primary)
        .first()
    )
    if not primary_client_contact:
        raise ValueError("No primary signer contact found for client")

    # Get secondary signer contact if exists
    secondary_client_contact = (
        db.query(ClientContact)
        .filter(ClientContact.client_id == client.id, ClientContact.signer_type == SignerType.secondary)
        .first()
    )

    # Get check mailing address
    check_address = claim.check_mailing_address
    if not check_address:
        raise ValueError("No check mailing address found for claim")

    properties = []
    total_amount = 0.0
    for prop in lead.properties:
        amount = float(prop.property_amount) if prop.property_amount else 0.0
        total_amount += amount
        properties.append(
            {
                "property_id": prop.property_id,
                "amount": _format_amount(prop.property_amount) if prop.property_amount else "",
            }
        )
    if not properties:
        raise ValueError("No linked properties to populate agreement")

    # Update client fields if provided
    if control_no:
        client.control_no = control_no
    if formation_state:
        client.formation_state = formation_state

    # Update claim fields
    if fee_flat:
        claim.fee_flat = float(fee_flat)
        claim.fee_pct = None
        claim.cdr_fee = float(fee_flat)
    else:
        fee_pct_val = float(fee_pct) if fee_pct else 10.0
        claim.fee_pct = fee_pct_val
        claim.fee_flat = None
        claim.cdr_fee = round(total_amount * (fee_pct_val / 100.0), 2)
    
    claim.addendum_yes = bool(addendum_yes)
    claim.total_properties = len(properties)
    claim.total_amount = total_amount

    cdr_profile = _load_cdr_profile()
    db.flush()

    if not claim.output_dir:
        claim.output_dir = str(OUTPUT_ROOT / f"claim-{claim.id}")
    output_dir = Path(claim.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = output_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    # Build primary contact payload
    primary_contact_name = f"{primary_client_contact.first_name} {primary_client_contact.last_name}".strip()
    primary_contact_payload = {
        "name": primary_contact_name,
        "phone": primary_client_contact.phone or "",
        "mail": f"{check_address.street}, {check_address.city} {check_address.state} {check_address.zip}",
        "email": primary_client_contact.email or "",
        "taxid_ssn": "",
    }
    
    # Build secondary contact payload if exists
    secondary_contact_payload = None
    if secondary_client_contact:
        secondary_contact_name = f"{secondary_client_contact.first_name} {secondary_client_contact.last_name}".strip()
        secondary_contact_payload = {
            "name": secondary_contact_name,
            "phone": secondary_client_contact.phone or "",
            "mail": f"{check_address.street}, {check_address.city} {check_address.state} {check_address.zip}",
            "email": secondary_client_contact.email or "",
            "taxid_ssn": "",
        }
    
    # Build meta with fee information
    fee_value = claim.cdr_fee if claim.cdr_fee else 0.0
    if claim.fee_flat:
        meta = {
            "cdr_fee_percentage": "",
            "cdr_fee_flat": str(claim.fee_flat),
            "addendum_yes": bool(addendum_yes),
            "cdr_control_no": client.control_no or "",
            "cdr_fee_amount": str(fee_value),
        }
    else:
        meta = {
            "cdr_fee_percentage": str(claim.fee_pct) if claim.fee_pct else "10",
            "cdr_fee_flat": "",
            "addendum_yes": bool(addendum_yes),
            "cdr_control_no": client.control_no or "",
            "cdr_fee_amount": str(fee_value),
        }

    recovery_field_mapping = build_recovery_mapping(properties, primary_contact_payload, meta, cdr_profile)
    ts_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    rec_output = generated_dir / f"UP-CDR2 Recovery Agreement_{ts_suffix}.pdf"
    ok_rec = fill_pdf_fields_reportlab(
        str(TEMPLATES_DIR / "UP-CDR2 Recovery Agreement.pdf"),
        recovery_field_mapping,
        str(rec_output),
    )
    if (not ok_rec) or (not rec_output.exists()):
        raise ValueError("Failed to generate Recovery Agreement PDF")

    business_payload = {
        "name": claim.entitled_business_name,
        "formation_state": client.formation_state or "",
        "fein": "",
        "control_no": client.control_no or "",
        "street": check_address.street,
        "city": check_address.city,
        "state": check_address.state,
        "zip": check_address.zip,
    }
    claimant_payload = {
        "name": primary_contact_name,
        "title": primary_client_contact.title or "",
        "email": primary_client_contact.email or "",
        "phone": primary_client_contact.phone or "",
        "mail": f"{check_address.street}, {check_address.city} {check_address.state} {check_address.zip}",
    }
    auth_field_mapping = build_auth_mapping(business_payload, claimant_payload, cdr_profile)
    auth_output = generated_dir / f"Recover_Authorization_Letter_{ts_suffix}.pdf"
    ok_auth = fill_pdf_fields_reportlab(
        str(TEMPLATES_DIR / "Recover_Authorization_Letter.pdf"),
        auth_field_mapping,
        str(auth_output),
    )
    if (not ok_auth) or (not auth_output.exists()):
        raise ValueError("Failed to generate Authorization Letter PDF")

    # Create separate events for each generated file
    agreement_event_payload = {
        "control_no": client.control_no or "",
        "formation_state": client.formation_state or "",
        "fee_pct": str(claim.fee_pct) if claim.fee_pct else "",
        "fee_flat": str(claim.fee_flat) if claim.fee_flat else "",
        "cdr_fee": str(claim.cdr_fee) if claim.cdr_fee else "",
        "addendum_yes": addendum_yes,
        "file_name": rec_output.name,
        "file_path": str(rec_output),
    }
    agreement_event = _record_event(db, claim, "agreement_file_generated", agreement_event_payload, user=user)
    
    authorization_event_payload = {
        "control_no": client.control_no or "",
        "formation_state": client.formation_state or "",
        "fee_pct": str(claim.fee_pct) if claim.fee_pct else "",
        "fee_flat": str(claim.fee_flat) if claim.fee_flat else "",
        "cdr_fee": str(claim.cdr_fee) if claim.cdr_fee else "",
        "addendum_yes": addendum_yes,
        "file_name": auth_output.name,
        "file_path": str(auth_output),
    }
    authorization_event = _record_event(db, claim, "authorization_file_generated", authorization_event_payload, user=user)
    
    db.add_all(
        [
            ClaimDocument(
                claim_id=claim.id,
                doc_type="agreement_generated",
                original_name=rec_output.name,
                file_path=str(rec_output),
                created_by=user,
            ),
            ClaimDocument(
                claim_id=claim.id,
                doc_type="authorization_generated",
                original_name=auth_output.name,
                file_path=str(auth_output),
                created_by=user,
            ),
        ]
    )
    db.commit()

    return {
        "claim_id": claim.id,
        "claim_slug": claim.claim_slug,
        "output_dir": claim.output_dir,
        "files": {
            "recovery_agreement": str(rec_output),
            "authorization_letter": str(auth_output),
        },
        "event_ids": [agreement_event.id, authorization_event.id],
    }


def list_events(db: Session, lead_id: int) -> List[Dict[str, Any]]:
    """List events for the latest claim on a lead."""
    claim = (
        db.query(Claim)
        .filter(Claim.lead_id == lead_id)
        .order_by(Claim.id.desc())
        .first()
    )
    if not claim:
        return []
    return list_events_for_claim(db, claim.id)


def list_events_for_claim(db: Session, claim_id: int) -> List[Dict[str, Any]]:
    events = (
        db.query(ClaimEvent)
        .filter(ClaimEvent.claim_id == claim_id)
        .order_by(ClaimEvent.created_at.desc())
        .all()
    )
    parsed = []
    for e in events:
        payload = e.payload
        try:
            payload = json.loads(payload) if isinstance(payload, str) else payload
        except Exception:
            pass
        parsed.append(
            {
                "id": e.id,
                "state": e.state,
                "payload": payload,
                "created_by": e.created_by,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
        )
    return parsed


def list_documents(db: Session, lead_id: int) -> List[Dict[str, Any]]:
    """List documents for the latest claim on a lead."""
    claim = (
        db.query(Claim)
        .filter(Claim.lead_id == lead_id)
        .order_by(Claim.id.desc())
        .first()
    )
    if not claim:
        return []
    return list_documents_for_claim(db, claim.id)


def list_documents_for_claim(db: Session, claim_id: int) -> List[Dict[str, Any]]:
    docs = (
        db.query(ClaimDocument)
        .filter(ClaimDocument.claim_id == claim_id)
        .order_by(ClaimDocument.created_at.desc())
        .all()
    )
    return [
        {
            "id": d.id,
            "doc_type": d.doc_type,
            "original_name": d.original_name,
            "file_path": d.file_path,
            "notes": d.notes,
            "created_by": d.created_by,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


def get_latest_claim_summary(db: Session, lead_id: int) -> Optional[Dict[str, Any]]:
    claim = (
        db.query(Claim)
        .filter(Claim.lead_id == lead_id)
        .order_by(Claim.id.desc())
        .first()
    )
    if not claim:
        return None
    # Derive current state from latest *status* event (skip file events)
    latest_event = (
        db.query(ClaimEvent)
        .filter(ClaimEvent.claim_id == claim.id)
        .filter(ClaimEvent.state.in_(CLAIM_STATUS_STATES))
        .order_by(ClaimEvent.created_at.desc())
        .first()
    )
    current_state = latest_event.state if latest_event else None
    
    # Get client data
    client = claim.client
    fee_display = None
    if claim.fee_flat:
        fee_display = f"${claim.fee_flat:,.2f}"
    elif claim.fee_pct:
        fee_display = f"{claim.fee_pct}%"
    
    return {
        "id": claim.id,
        "claim_slug": claim.claim_slug,
        "control_no": client.control_no if client else None,
        "formation_state": client.formation_state if client else None,
        "fee_pct": str(claim.fee_pct) if claim.fee_pct else None,
        "fee_flat": str(claim.fee_flat) if claim.fee_flat else None,
        "fee_display": fee_display,
        "addendum_yes": claim.addendum_yes,
        "output_dir": claim.output_dir,
        "created_at": claim.created_at.isoformat() if claim.created_at else None,
        "current_state": current_state,
    }

