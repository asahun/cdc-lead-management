"""Lead agent intelligence routes (v1)."""

import json
import logging
import os
from typing import Any

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from models import LeadAgentIntel
from services.property_service import get_property_details_for_lead
from utils import get_lead_or_404

logger = logging.getLogger(__name__)

router = APIRouter()

AI_AGENT_URL = os.getenv("AI_AGENT_URL", "http://localhost:8088")
AI_AGENT_TIMEOUT = int(os.getenv("AI_AGENT_TIMEOUT", "600"))  # default 10 minutes


def _normalize_state(value: str | None) -> str:
    state = (value or "GA").strip().upper()
    return state if len(state) == 2 else "GA"


def _build_payload(lead, property_details: dict[str, Any], property_ids: list[str]) -> dict[str, Any]:
    report_year_value = None
    if property_details.get("reportyear"):
        try:
            report_year_value = int(str(property_details.get("reportyear")))
        except (TypeError, ValueError):
            report_year_value = None
    return {
        "business_id": str(lead.id),
        "business_name": lead.owner_name,
        "state": _normalize_state(property_details.get("ownerstate")),
        "property_ids": property_ids or None,
        "holder_name_on_record": property_details.get("holdername") or None,
        "last_activity_date": property_details.get("lastactivitydate") or None,
        "property_report_year": report_year_value,
        "city": property_details.get("ownercity") or None,
        "ownerrelation": property_details.get("ownerrelation") or None,
        "propertytypedescription": property_details.get("propertytypedescription") or None,
        "address_source": "property_mailing",
        "holder_known_address": {
            "street": property_details.get("owneraddress1") or "",
            "street2": property_details.get("owneraddress2") or "",
            "street3": property_details.get("owneraddress3") or "",
            "city": property_details.get("ownercity") or "",
            "state": property_details.get("ownerstate") or "",
            "zip": property_details.get("ownerzipcode") or "",
        },
    }


def _fallback_response(payload: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "input": payload,
        "analysis": {},
        "audit": {"steps": [], "errors": [error]},
    }


@router.get("/leads/{lead_id}/agent-intel/latest")
def get_latest_agent_intel(lead_id: int, db: Session = Depends(get_db)):
    get_lead_or_404(db, lead_id)
    latest = (
        db.query(LeadAgentIntel)
        .filter(LeadAgentIntel.lead_id == lead_id)
        .order_by(LeadAgentIntel.created_at.desc())
        .first()
    )
    if not latest:
        return {"result": None}

    try:
        result = json.loads(latest.response_payload)
    except json.JSONDecodeError:
        result = None

    return {
        "result": result,
        "status": latest.status,
        "created_at": latest.created_at.isoformat() if latest.created_at else None,
    }


@router.post("/leads/{lead_id}/agent-intel/run")
def run_agent_intel(lead_id: int, db: Session = Depends(get_db)):
    lead = get_lead_or_404(db, lead_id)
    property_details = get_property_details_for_lead(db, lead)
    if not property_details:
        raise HTTPException(status_code=404, detail="Linked property record not found for this lead.")

    property_ids = [p.property_id for p in lead.properties if p.property_id]
    payload = _build_payload(lead, property_details, property_ids)

    status = "completed"
    error_message = None
    try:
        response = requests.post(
            f"{AI_AGENT_URL}/run",
            json=payload,
            timeout=AI_AGENT_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
    except Exception as exc:
        logger.warning("agent-intel call failed: %s", exc)
        status = "error"
        error_message = str(exc)
        result = _fallback_response(payload, error_message)

    db.query(LeadAgentIntel).filter(LeadAgentIntel.lead_id == lead.id).delete()

    record = LeadAgentIntel(
        lead_id=lead.id,
        property_id=property_details.get("propertyid"),
        property_raw_hash=property_details.get("raw_hash") or property_details.get("row_hash"),
        request_payload=json.dumps(payload, default=str),
        response_payload=json.dumps(result, default=str),
        status=status,
        error_message=error_message,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "result": result,
        "status": status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
