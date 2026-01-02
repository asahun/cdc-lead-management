"""
Lead entity intelligence routes.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from db import get_db
from services.exceptions import GPTConfigError, GPTServiceError, SOSDataError
from services.gpt_service import fetch_entity_intelligence
from services.property_service import build_gpt_payload, get_property_details_for_lead
from services.sos_service import SOSService
from utils import get_lead_or_404

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/leads/{lead_id}/entity-intel")
async def lead_entity_intelligence(
    lead_id: int,
    db: Session = Depends(get_db),
):
    logger.info("lead_entity_intelligence: Request for lead_id=%s", lead_id)
    lead = get_lead_or_404(db, lead_id)

    prop = get_property_details_for_lead(db, lead)
    logger.debug("lead_entity_intelligence: Property found: %s", prop is not None)

    if not prop:
        raise HTTPException(
            status_code=404,
            detail="Linked property record not found for this lead.",
        )

    payload = build_gpt_payload(lead, prop)
    logger.debug(
        "lead_entity_intelligence: GPT payload built: business_name='%s', property_state='%s'",
        payload.get("business_name"),
        payload.get("property_state"),
    )

    try:
        analysis = await run_in_threadpool(fetch_entity_intelligence, payload, db)
        logger.info(
            "lead_entity_intelligence: Analysis complete, response keys: %s",
            list(analysis.keys()) if analysis else "None",
        )

        new_fields = [
            "status_profile",
            "address_profile",
            "contact_recommendation",
            "data_gaps",
            "ga_entity_mapping",
            "entitlement",
        ]
        for field in new_fields:
            if field in analysis:
                field_value = analysis[field]
                if isinstance(field_value, dict):
                    logger.debug(
                        "lead_entity_intelligence: %s present with keys: %s",
                        field,
                        list(field_value.keys()),
                    )
                elif isinstance(field_value, list):
                    logger.debug(
                        "lead_entity_intelligence: %s present as list with %s items",
                        field,
                        len(field_value),
                    )
                else:
                    logger.debug("lead_entity_intelligence: %s = %s", field, field_value)
            else:
                logger.warning("lead_entity_intelligence: %s is MISSING from analysis response", field)

        logger.debug(
            "lead_entity_intelligence: Analysis preview - chain_status=%s, current_entity=%s",
            analysis.get("chain_assessment", {}).get("chain_status", "N/A"),
            analysis.get("current_entity", {}).get("legal_name", "N/A"),
        )
    except GPTConfigError as exc:
        logger.error("lead_entity_intelligence: GPTConfigError: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GPTServiceError as exc:
        logger.error("lead_entity_intelligence: GPTServiceError: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    response = {"input": payload, "analysis": analysis}
    logger.debug(
        "lead_entity_intelligence: Returning response with input keys: %s, analysis keys: %s",
        list(response.get("input", {}).keys()),
        list(response.get("analysis", {}).keys()),
    )
    return response


@router.get("/leads/{lead_id}/entity-intel/sos-options")
async def lead_entity_intel_sos_options(
    lead_id: int,
    flip: bool = Query(False, description="Apply flipped search (move first token to end)"),
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)
    prop = get_property_details_for_lead(db, lead)
    if not prop:
        raise HTTPException(status_code=404, detail="Linked property record not found for this lead.")

    owner_name = lead.owner_name or prop.get("ownername") or ""
    from services.property_service import flip_allowed, normalize_property_owner_name, reorder_first_token_to_end

    base_normalized = normalize_property_owner_name(owner_name)
    if not base_normalized:
        return {
            "search_name_used": "",
            "flip_applied": False,
            "flip_allowed": False,
            "sos_records": [],
        }

    flip_allowed_result = flip_allowed(base_normalized, owner_name)
    if flip and not flip_allowed_result:
        raise HTTPException(
            status_code=400,
            detail="Flip search not allowed for this name (requires exactly 3 tokens and no suffix/special chars).",
        )

    sos_service = SOSService(db)
    search_name_used = reorder_first_token_to_end(base_normalized) if flip else base_normalized
    try:
        sos_records = sos_service.search_by_normalized_name(search_name_used)
    except SOSDataError as exc:
        logger.error("lead_entity_intel_sos_options: SOS query failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to query SOS records") from exc

    return {
        "search_name_used": search_name_used,
        "flip_applied": flip,
        "flip_allowed": flip_allowed_result,
        "sos_records": sos_records,
    }


@router.post("/leads/{lead_id}/entity-intel/run")
async def lead_entity_intelligence_run(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)
    prop = get_property_details_for_lead(db, lead)
    if not prop:
        raise HTTPException(status_code=404, detail="Linked property record not found for this lead.")

    try:
        body = await request.json()
    except Exception:
        body = {}

    selected_sos_record = body.get("selected_sos_record") or None
    sos_search_name_used = body.get("sos_search_name_used") or None
    flip_applied = bool(body.get("flip_applied", False))

    payload = build_gpt_payload(lead, prop)
    payload.update(
        {
            "selected_sos_record": selected_sos_record,
            "sos_search_name_used": sos_search_name_used,
            "skip_sos_lookup": True,
        }
    )

    try:
        analysis = await run_in_threadpool(fetch_entity_intelligence, payload, db)
    except GPTConfigError as exc:
        logger.error("lead_entity_intelligence_run: GPTConfigError: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GPTServiceError as exc:
        logger.error("lead_entity_intelligence_run: GPTServiceError: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    gpt_redacted_sos_data = None
    if selected_sos_record:
        sos_service = SOSService(db)
        gpt_redacted_sos_data = sos_service.redact_record(selected_sos_record)

    response = {
        "input": payload,
        "analysis": analysis,
        "selected_sos_data": selected_sos_record,
        "gpt_redacted_sos_data": gpt_redacted_sos_data,
        "meta": {
            "sos_search_name_used": sos_search_name_used,
            "flip_applied": flip_applied,
        },
    }
    return response
