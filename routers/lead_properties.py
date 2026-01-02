"""
Lead property assignment routes.
"""

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from db import get_db
from helpers.property_serialization import related_property_payload
from models import Lead, LeadProperty
from services.property_service import mark_property_assigned
from utils import get_lead_or_404

router = APIRouter()


@router.post("/leads/{lead_id}/properties/add")
def add_property_to_lead(
    lead_id: int,
    property_id: str = Form(...),
    property_raw_hash: str = Form(...),
    property_amount: float | None = Form(None),
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)

    existing = db.scalar(
        select(LeadProperty).where(LeadProperty.property_raw_hash == property_raw_hash)
    )
    if existing:
        existing_lead = db.get(Lead, existing.lead_id)
        raise HTTPException(
            status_code=400,
            detail=f"Property already assigned to Lead #{existing_lead.id}",
        )

    new_property = LeadProperty(
        lead_id=lead.id,
        property_id=property_id,
        property_raw_hash=property_raw_hash,
        property_amount=property_amount,
        is_primary=False,
    )
    db.add(new_property)
    mark_property_assigned(db, property_raw_hash, property_id)
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)


@router.post("/leads/{lead_id}/properties/{property_id}/remove")
def remove_property_from_lead(
    lead_id: int,
    property_id: str,
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)

    prop = db.scalar(
        select(LeadProperty).where(
            LeadProperty.lead_id == lead_id, LeadProperty.property_id == property_id
        )
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    property_count = db.scalar(
        select(func.count(LeadProperty.id)).where(LeadProperty.lead_id == lead_id)
    )
    if property_count <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the only property from a lead.",
        )

    if prop.is_primary:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the primary property. Set another property as primary first.",
        )

    property_raw_hash = prop.property_raw_hash
    db.delete(prop)

    from services.property_service import unmark_property_if_unused

    unmark_property_if_unused(db, property_raw_hash, property_id)
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)


@router.post("/leads/{lead_id}/properties/{property_id}/set-primary")
def set_primary_property(
    lead_id: int,
    property_id: str,
    db: Session = Depends(get_db),
):
    get_lead_or_404(db, lead_id)

    prop = db.scalar(
        select(LeadProperty).where(
            LeadProperty.lead_id == lead_id, LeadProperty.property_id == property_id
        )
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    db.execute(
        update(LeadProperty).where(LeadProperty.lead_id == lead_id).values(is_primary=False)
    )

    prop.is_primary = True
    db.commit()

    return RedirectResponse(url=f"/leads/{lead_id}/edit", status_code=303)


@router.get("/leads/{lead_id}/properties/related")
def get_related_properties_for_lead(
    lead_id: int,
    flip: bool = Query(False, description="Include flipped name matching"),
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)

    from services.property_service import find_related_properties_by_owner_name

    related_props = find_related_properties_by_owner_name(
        db,
        lead.owner_name,
        exclude_lead_id=lead_id,
        flip=flip,
    )

    result = [related_property_payload(prop, include_address=True) for prop in related_props]
    return JSONResponse(content={"properties": result})


@router.get("/properties/related")
def get_related_properties_by_owner_name(
    owner_name: str = Query(..., description="Owner name to search for"),
    exclude_lead_id: int | None = Query(None, description="Lead ID to exclude from assignment check"),
    db: Session = Depends(get_db),
):
    from services.property_service import find_related_properties_by_owner_name

    related_props = find_related_properties_by_owner_name(
        db,
        owner_name,
        exclude_lead_id=exclude_lead_id,
    )

    result = []
    for prop in related_props:
        already_assigned = (
            db.scalar(
                select(LeadProperty).where(LeadProperty.property_raw_hash == prop.get("raw_hash"))
            )
            is not None
        )

        if not already_assigned:
            result.append(related_property_payload(prop))

    return JSONResponse(content={"properties": result})


@router.post("/leads/{lead_id}/properties/add-bulk")
def add_properties_bulk(
    lead_id: int,
    property_ids: str = Form(...),
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(db, lead_id)

    try:
        properties_data = json.loads(property_ids)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid property_ids JSON")

    if not isinstance(properties_data, list):
        raise HTTPException(status_code=400, detail="property_ids must be an array")

    added_count = 0
    errors = []

    for prop_data in properties_data:
        property_id = prop_data.get("property_id")
        property_raw_hash = prop_data.get("property_raw_hash")
        property_amount = prop_data.get("property_amount")

        if not property_id or not property_raw_hash:
            errors.append("Missing property_id or property_raw_hash for one property")
            continue

        existing = db.scalar(
            select(LeadProperty).where(LeadProperty.property_raw_hash == property_raw_hash)
        )
        if existing:
            if existing.lead_id == lead_id:
                continue
            existing_lead = db.get(Lead, existing.lead_id)
            errors.append(f"Property {property_id} already assigned to Lead #{existing_lead.id}")
            continue

        new_property = LeadProperty(
            lead_id=lead.id,
            property_id=property_id,
            property_raw_hash=property_raw_hash,
            property_amount=property_amount,
            is_primary=False,
        )
        db.add(new_property)
        mark_property_assigned(db, property_raw_hash, property_id)
        added_count += 1

    db.commit()

    if errors:
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "added_count": added_count,
                "errors": errors,
                "message": f"Added {added_count} properties. {len(errors)} errors occurred.",
            },
        )

    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)
