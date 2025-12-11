"""
Property routes - handles all property-related endpoints.
"""

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, cast, String, exists, and_

from db import get_db
from models import OwnerRelationshipAuthority, BusinessLead
from services.property_service import (
    get_available_years,
    get_property_table_for_year,
    get_property_by_id,
    get_property_by_raw_hash,
    get_property_by_order,
    property_navigation_info,
    DEFAULT_YEAR,
    PROPERTY_MIN_AMOUNT,
)
from utils import previous_monday_cutoff
from helpers.phone_scripts import load_phone_scripts, get_phone_scripts_json

# Import shared resources from main (will be passed in or imported)
# For now, we'll import them - in a full refactor, these would be in a shared config module
from fastapi.templating import Jinja2Templates
import json

# Import shared templates from main to ensure filters are registered
templates = None  # Will be set by main.py
PAGE_SIZE = 20

PHONE_SCRIPTS = load_phone_scripts()
PHONE_SCRIPTS_JSON = get_phone_scripts_json()

def _build_phone_script_context(
    owner_name: str | None,
    property_id: str | None,
    property_amount,
    property_details: dict | None,
):
    amount_value = None
    if property_details and property_details.get("propertyamount") not in (None, ""):
        try:
            amount_value = float(property_details.get("propertyamount"))
        except (ValueError, TypeError):
            pass
    
    return {
        "owner_name": owner_name or "",
        "property_id": property_id or "",
        "property_amount": amount_value,
    }

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
@router.get("/properties", response_class=HTMLResponse)
def list_properties(
    request: Request,
    page: int = 1,
    q: str | None = None,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    claim_authority: str | None = Query(None, description="Claim Authority: Unknown, Single, Joint"),
    db: Session = Depends(get_db),
):
    if page < 1:
        page = 1

    # Default to current year if not specified
    if not year:
        year = DEFAULT_YEAR
    
    # Validate year exists
    available_years = get_available_years(db)
    if year not in available_years:
        year = DEFAULT_YEAR
    
    # Get dynamic table for the selected year
    prop_table = get_property_table_for_year(year)
    
    # Build filters using dynamic table
    filters = [prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT]
    
    cutoff = previous_monday_cutoff()
    if prop_table.c.last_seen is not None:
        filters.append(prop_table.c.last_seen >= cutoff)

    if q:
        pattern = f"%{q}%"
        prop_id_text = cast(prop_table.c.propertyid, String)
        filters.append(
            or_(
                prop_id_text.ilike(pattern),
                prop_table.c.ownername.ilike(pattern),
            )
        )

    # Join with owner_relationship_authority and filter by Claim_Authority if specified
    claim_authority_filter = None
    if claim_authority is None:
        claim_authority_filter = "Single"
        claim_authority_display = "Single"
    elif claim_authority.strip() == "":
        claim_authority_filter = None
        claim_authority_display = ""
    else:
        claim_authority_filter = claim_authority
        claim_authority_display = claim_authority
    
    join_condition = None
    if claim_authority_filter and claim_authority_filter.lower() in ("unknown", "single", "joint"):
        join_condition = func.trim(OwnerRelationshipAuthority.code) == func.trim(prop_table.c.ownerrelation)
        filters.append(
            func.upper(func.trim(OwnerRelationshipAuthority.Claim_Authority)) == claim_authority_filter.upper()
        )

    property_ordering = (prop_table.c.propertyamount.desc(), prop_table.c.row_hash.asc())

    if join_condition is not None:
        count_stmt = (
            select(func.count())
            .select_from(prop_table)
            .join(OwnerRelationshipAuthority, join_condition)
            .where(*filters)
        )

        ranked_stmt = (
            select(
                prop_table.c.row_hash.label("raw_hash"),
                prop_table.c.propertyid.label("propertyid"),
                prop_table.c.ownername.label("ownername"),
                prop_table.c.propertyamount.label("propertyamount"),
                prop_table.c.assigned_to_lead.label("assigned_to_lead"),
                func.row_number().over(order_by=property_ordering).label("order_id"),
            )
            .join(OwnerRelationshipAuthority, join_condition)
            .where(*filters)
        )
    else:
        count_stmt = (
            select(func.count())
            .select_from(prop_table)
            .where(*filters)
        )

        ranked_stmt = (
            select(
                prop_table.c.row_hash.label("raw_hash"),
                prop_table.c.propertyid.label("propertyid"),
                prop_table.c.ownername.label("ownername"),
                prop_table.c.propertyamount.label("propertyamount"),
                prop_table.c.assigned_to_lead.label("assigned_to_lead"),
                func.row_number().over(order_by=property_ordering).label("order_id"),
            )
            .where(*filters)
        )

    ranked_subq = ranked_stmt.subquery()
    stmt = (
        select(ranked_subq)
        .order_by(ranked_subq.c.order_id)
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )

    rows_result = db.execute(stmt).mappings().all()
    rows = [dict(row) for row in rows_result]
    total = db.scalar(count_stmt) or 0

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1

    return templates.TemplateResponse(
        "properties.html",
        {
            "request": request,
            "properties": rows,
            "page": page,
            "total_pages": total_pages,
            "q": q or "",
            "total": total,
            "year": year,
            "available_years": available_years,
            "claim_authority": claim_authority_display,
        },
    )


@router.get("/properties/{property_id}", response_class=HTMLResponse)
def property_detail(
    request: Request,
    property_id: str,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    if not year:
        year = DEFAULT_YEAR
    
    prop = get_property_by_id(db, property_id, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = property_navigation_info(db, prop["raw_hash"], year)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.get("assigned_to_lead")

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"] if show_navigation else None,
            "next_order_id": nav["next_order_id"] if show_navigation else None,
            "prev_raw_hash": nav["prev_hash"] if show_navigation else None,
            "next_raw_hash": nav["next_hash"] if show_navigation else None,
            "show_navigation": show_navigation,
            "show_add_to_lead": show_add_to_lead,
        },
    )


@router.get("/api/properties/{property_id}")
def property_detail_json(
    property_id: str,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    if not year:
        year = DEFAULT_YEAR
    
    prop = get_property_by_id(db, property_id, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = property_navigation_info(db, prop["raw_hash"], year)

    return JSONResponse(
        {
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"],
            "next_order_id": nav["next_order_id"],
            "prev_raw_hash": nav["prev_hash"],
            "next_raw_hash": nav["next_hash"],
        }
    )


@router.get("/properties/by_hash/{raw_hash}", response_class=HTMLResponse)
def property_detail_by_hash(
    request: Request,
    raw_hash: str,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    if not year:
        year = DEFAULT_YEAR
    
    prop = get_property_by_raw_hash(db, raw_hash, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = property_navigation_info(db, prop["raw_hash"], year)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.get("assigned_to_lead")

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"] if show_navigation else None,
            "next_order_id": nav["next_order_id"] if show_navigation else None,
            "prev_raw_hash": nav["prev_hash"] if show_navigation else None,
            "next_raw_hash": nav["next_hash"] if show_navigation else None,
            "show_navigation": show_navigation,
            "show_add_to_lead": show_add_to_lead,
        },
    )


@router.get("/properties/by_order/{order_id}", response_class=HTMLResponse)
def property_detail_by_order(
    request: Request,
    order_id: int,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    if not year:
        year = DEFAULT_YEAR
    
    prop = get_property_by_order(db, order_id, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = property_navigation_info(db, prop["raw_hash"], year)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.get("assigned_to_lead")

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"] if show_navigation else None,
            "next_order_id": nav["next_order_id"] if show_navigation else None,
            "prev_raw_hash": nav["prev_hash"] if show_navigation else None,
            "next_raw_hash": nav["next_hash"] if show_navigation else None,
            "show_navigation": show_navigation,
            "show_add_to_lead": show_add_to_lead,
        },
    )


@router.get("/api/properties/by_order/{order_id}")
def property_detail_json_by_order(
    order_id: int,
    year: str | None = Query(None, description="Year for property table (e.g., 2025)"),
    db: Session = Depends(get_db),
):
    if not year:
        year = DEFAULT_YEAR
    
    prop = get_property_by_order(db, order_id, year)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = property_navigation_info(db, prop["raw_hash"], year)

    return JSONResponse(
        {
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"],
            "next_order_id": nav["next_order_id"],
            "prev_raw_hash": nav["prev_hash"],
            "next_raw_hash": nav["next_hash"],
        }
    )

