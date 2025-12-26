import os
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

from sqlalchemy.orm import Session

from models import Lead, LeadContact, LeadProperty, LeadStatus, LeadClient, LeadClientEvent
from scripts.fill_recovery_agreement import build_field_mapping as build_recovery_mapping
from scripts.fill_recover_authorization_letter import build_field_mapping as build_auth_mapping
from scripts.pdf_fill_engine import fill_pdf_fields
import json


CLIENT_SLUG_PREFIX = "client-"
TEMPLATES_DIR = Path("scripts/pdf_templates")
OUTPUT_ROOT = Path("scripts/pdf_output")
CDR_PROFILE_PATH = Path("scripts/data/cdr_profile.json")


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


def _ensure_client(db: Session, lead_id: int, control_no: str, formation_state: str, fee_pct: str, addendum_yes: bool) -> LeadClient:
    slug = f"{CLIENT_SLUG_PREFIX}{lead_id}"
    output_dir = OUTPUT_ROOT / slug
    client = db.query(LeadClient).filter(LeadClient.lead_id == lead_id).one_or_none()
    if client is None:
        client = LeadClient(
            lead_id=lead_id,
            slug=slug,
            control_no=control_no,
            formation_state=formation_state,
            fee_pct=str(fee_pct),
            addendum_yes=bool(addendum_yes),
            output_dir=str(output_dir),
        )
        db.add(client)
    else:
        client.control_no = control_no
        client.formation_state = formation_state
        client.fee_pct = str(fee_pct)
        client.addendum_yes = bool(addendum_yes)
        client.output_dir = str(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return client


def _record_event(db: Session, client: LeadClient, state: str, payload: Dict[str, Any], user: str = None) -> LeadClientEvent:
    # Store payload as JSON string for the Text column
    payload_json = json.dumps(payload)
    event = LeadClientEvent(
        client_id=client.id,
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
    lead = db.query(Lead).filter(Lead.id == lead_id).one_or_none()
    if not lead:
        raise ValueError("Lead not found")
    if lead.status != LeadStatus.response_received:
        raise ValueError("Lead status must be response_received to generate agreements")

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

    client = _ensure_client(db, lead_id, control_no, formation_state, fee_pct, addendum_yes)
    db.flush()

    cdr_profile = _load_cdr_profile()
    output_dir = Path(client.output_dir)

    # Recovery Agreement payload
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
    rec_output = output_dir / f"UP-CDR2 Recovery Agreement_{ts_suffix}.pdf"
    ok_rec = fill_pdf_fields(
        str(TEMPLATES_DIR / "UP-CDR2 Recovery Agreement.pdf"),
        recovery_field_mapping,
        str(rec_output),
        draw_fallback=False,
        lock_fields=True,
    )
    if (not ok_rec) or (not rec_output.exists()):
        raise ValueError("Failed to generate Recovery Agreement PDF")

    # Authorization Letter payload
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
    auth_output = output_dir / f"Recover_Authorization_Letter_{ts_suffix}.pdf"
    ok_auth = fill_pdf_fields(
        str(TEMPLATES_DIR / "Recover_Authorization_Letter.pdf"),
        auth_field_mapping,
        str(auth_output),
        draw_fallback=False,
        lock_fields=True,
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
    event = _record_event(db, client, "agreement_generated", payload_snapshot, user=user)
    db.commit()

    return {
        "client_id": client.id,
        "client_slug": client.slug,
        "output_dir": client.output_dir,
        "files": payload_snapshot["files"],
        "event_id": event.id,
    }


def list_events(db: Session, lead_id: int) -> List[Dict[str, Any]]:
    client = db.query(LeadClient).filter(LeadClient.lead_id == lead_id).one_or_none()
    if not client:
        return []
    events = (
        db.query(LeadClientEvent)
        .filter(LeadClientEvent.client_id == client.id)
        .order_by(LeadClientEvent.created_at.desc())
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

