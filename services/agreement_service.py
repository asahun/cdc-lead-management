import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from models import Lead, LeadContact, LeadProperty, LeadStatus, Claim, ClaimEvent, ClaimDocument
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


def _ensure_claim(
    db: Session,
    lead: Lead,
    control_no: str,
    formation_state: str,
    fee_pct: str,
    addendum_yes: bool,
    primary_contact: LeadContact,
    cdr_profile: Dict[str, Any],
) -> Claim:
    existing = (
        db.query(Claim)
        .filter(Claim.lead_id == lead.id)
        .order_by(Claim.id.desc())
        .first()
    )
    if existing:
        claim = existing
        claim.control_no = control_no
        claim.formation_state = formation_state
        claim.fee_pct = str(fee_pct)
        claim.addendum_yes = bool(addendum_yes)
    else:
        claim = Claim(
            lead_id=lead.id,
            claim_slug=f"claim-{lead.id}-{int(datetime.utcnow().timestamp())}",
            business_name=lead.owner_name,
            formation_state=formation_state,
            control_no=control_no,
            fee_pct=str(fee_pct),
            addendum_yes=bool(addendum_yes),
            cdr_identifier=cdr_profile.get("cdr_identifier", ""),
            cdr_agent_name=cdr_profile.get("agent_name", ""),
            primary_contact_name=primary_contact.contact_name,
            primary_contact_title=primary_contact.title or "",
            primary_contact_email=primary_contact.email,
            primary_contact_phone=primary_contact.phone,
            primary_contact_mail=f"{primary_contact.address_street}, {primary_contact.address_city} {primary_contact.address_state} {primary_contact.address_zipcode}",
            output_dir=None,
        )
        db.add(claim)
    return claim


def create_claim_from_lead(
    db: Session,
    lead_id: int,
    control_no: str,
    formation_state: str,
    fee_pct: str,
    addendum_yes: bool,
    user: str = None,
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
    claim = _ensure_claim(
        db,
        lead,
        control_no,
        formation_state,
        fee_pct,
        addendum_yes,
        primary_contact,
        cdr_profile,
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
) -> Dict[str, Any]:
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise ValueError("Claim not found")
    lead = claim.lead
    if not lead:
        raise ValueError("Lead not found for claim")

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

    properties = []
    for prop in lead.properties:
        properties.append(
            {
                "property_id": prop.property_id,
                "amount": _format_amount(prop.property_amount) if prop.property_amount else "",
            }
        )
    if not properties:
        raise ValueError("No linked properties to populate agreement")

    # Update claim snapshot fields
    claim.control_no = control_no
    claim.formation_state = formation_state
    claim.fee_pct = str(fee_pct)
    claim.addendum_yes = bool(addendum_yes)
    cdr_profile = _load_cdr_profile()
    claim.cdr_identifier = cdr_profile.get("cdr_identifier", "")
    claim.cdr_agent_name = cdr_profile.get("agent_name", "")

    db.flush()

    if not claim.output_dir:
        claim.output_dir = str(OUTPUT_ROOT / f"claim-{claim.id}")
    output_dir = Path(claim.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_dir = output_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    primary_contact_payload = {
        "name": primary_contact.contact_name,
        "phone": primary_contact.phone,
        "mail": f"{primary_contact.address_street}, {primary_contact.address_city} {primary_contact.address_state} {primary_contact.address_zipcode}",
        "email": primary_contact.email,
        "taxid_ssn": "",
    }
    meta = {
        "cdr_fee_percentage": str(fee_pct),
        "addendum_yes": bool(addendum_yes),
        "cdr_control_no": control_no,
        "cdr_fee_amount": "",
        "cdr_fee_flat": 10.00,
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
        "name": lead.owner_name,
        "formation_state": formation_state,
        "fein": "",
        "control_no": control_no,
        "street": primary_contact.address_street,
        "city": primary_contact.address_city,
        "state": primary_contact.address_state,
        "zip": primary_contact.address_zipcode,
    }
    claimant_payload = {
        "name": primary_contact.contact_name,
        "title": primary_contact.title or "",
        "email": primary_contact.email,
        "phone": primary_contact.phone,
        "mail": f"{primary_contact.address_street}, {primary_contact.address_city} {primary_contact.address_state} {primary_contact.address_zipcode}",
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

    payload_snapshot = {
        "control_no": control_no,
        "formation_state": formation_state,
        "fee_pct": fee_pct,
        "addendum_yes": addendum_yes,
        "files": {
            "recovery_agreement": str(rec_output),
            "authorization_letter": str(auth_output),
        },
    }
    event = _record_event(db, claim, "agreement_generated", payload_snapshot, user=user)
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
        "files": payload_snapshot["files"],
        "event_id": event.id,
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
    return {
        "id": claim.id,
        "claim_slug": claim.claim_slug,
        "control_no": claim.control_no,
        "formation_state": claim.formation_state,
        "fee_pct": claim.fee_pct,
        "addendum_yes": claim.addendum_yes,
        "output_dir": claim.output_dir,
        "created_at": claim.created_at.isoformat() if claim.created_at else None,
        "current_state": current_state,
    }

