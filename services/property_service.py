"""
Property service - handles all property-related business logic.
"""

from decimal import Decimal
from typing import Optional
import re

from sqlalchemy.orm import Session
from sqlalchemy import select, func, update, cast, String, Table, MetaData, inspect

from db import engine
from models import PropertyView, BusinessLead, LeadProperty
from helpers.property_helpers import get_primary_property

# Constants
PROPERTY_MIN_AMOUNT = Decimal("10000")
DEFAULT_YEAR = "2025"

# Cache for available years
_YEAR_TABLES_LIST: Optional[list[str]] = None


def get_available_years(db: Session) -> list[str]:
    """Discover available year tables from database."""
    global _YEAR_TABLES_LIST
    
    if _YEAR_TABLES_LIST is not None:
        return _YEAR_TABLES_LIST
    
    inspector = inspect(engine)
    all_tables = inspector.get_table_names()
    
    # Filter tables matching pattern ucp_main_year_e_YYYY
    year_tables = []
    for table_name in all_tables:
        if table_name.startswith("ucp_main_year_e_"):
            # Extract year from table name (e.g., "ucp_main_year_e_2025" -> "2025")
            year_match = re.search(r"ucp_main_year_e_(\d{4})$", table_name)
            if year_match:
                year = year_match.group(1)
                year_tables.append(year)
    
    # Sort descending (newest first)
    year_tables.sort(reverse=True)
    _YEAR_TABLES_LIST = year_tables
    return year_tables


def get_property_table_for_year(year: str | None = None) -> Table:
    """Get SQLAlchemy Table object for the specified year's property table."""
    if not year:
        year = DEFAULT_YEAR
    
    table_name = f"ucp_main_year_e_{year}"
    
    # Check if table exists
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=f"Property table for year {year} not found"
        )
    
    # Use reflection to get the table
    metadata = MetaData()
    return Table(
        table_name,
        metadata,
        autoload_with=engine,
        schema=None
    )


def build_property_select(prop_table):
    """Build the common SELECT statement for property lookups."""
    return select(
        prop_table.c.row_hash.label("raw_hash"),  # Label as raw_hash for consistency
        prop_table.c.propertyid,
        prop_table.c.ownername,
        prop_table.c.propertyamount,
        prop_table.c.assigned_to_lead,
        prop_table.c.owneraddress1,
        prop_table.c.owneraddress2,
        prop_table.c.owneraddress3,
        prop_table.c.ownercity,
        prop_table.c.ownerstate,
        prop_table.c.ownerzipcode,
        prop_table.c.ownerrelation,
        prop_table.c.lastactivitydate,
        prop_table.c.reportyear,
        prop_table.c.holdername,
        prop_table.c.propertytypedescription,
    ).where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)


def get_property_by_id(db: Session, property_id: str, year: str | None = None) -> dict | None:
    """Get property by ID from the specified year's table. Returns dict with property data."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = get_property_table_for_year(year)
    
    result = db.execute(
        build_property_select(prop_table)
        .where(cast(prop_table.c.propertyid, String) == property_id)  # Cast to match text type
        .limit(1)
    ).first()
    
    if result:
        return dict(result._mapping)
    return None


def get_property_by_raw_hash(db: Session, raw_hash: str, year: str | None = None) -> dict | None:
    """Get property by raw hash from the specified year's table. Returns dict with property data."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = get_property_table_for_year(year)
    
    result = db.execute(
        build_property_select(prop_table)
        .where(prop_table.c.row_hash == raw_hash)  # Database column is "row_hash"
        .limit(1)
    ).first()
    
    if result:
        return dict(result._mapping)
    return None


def get_raw_hash_for_order(db: Session, order_id: int, year: str | None = None) -> str | None:
    """Get raw hash for a property by order ID from the specified year's table."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = get_property_table_for_year(year)
    property_ordering = (prop_table.c.propertyamount.desc(), prop_table.c.row_hash.asc())
    
    ranked = (
        select(
            prop_table.c.row_hash.label("raw_hash"),  # Database column is "row_hash", label as "raw_hash"
            func.row_number().over(order_by=property_ordering).label("order_id"),
        )
        .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
        .subquery()
    )
    return db.scalar(
        select(ranked.c.raw_hash).where(ranked.c.order_id == order_id)
    )


def get_property_by_order(db: Session, order_id: int, year: str | None = None) -> dict | None:
    """Get property by order ID from the specified year's table."""
    if not year:
        year = DEFAULT_YEAR
    
    raw_hash = get_raw_hash_for_order(db, order_id, year)
    if not raw_hash:
        return None
    return get_property_by_raw_hash(db, raw_hash, year)


def get_property_details_for_lead(db: Session, lead: BusinessLead, year: str | None = None) -> dict | None:
    """Get property details for a lead, trying to find it in the specified year's table."""
    if not year:
        year = DEFAULT_YEAR
    
    # Get primary property
    primary_prop = get_primary_property(lead)
    if not primary_prop:
        return None
    
    # Try all available years if property not found in specified year
    available_years = get_available_years(db)
    years_to_try = [year] + [y for y in available_years if y != year]
    
    for try_year in years_to_try:
        if primary_prop.property_raw_hash:
            prop = get_property_by_raw_hash(db, primary_prop.property_raw_hash, try_year)
            if prop:
                return prop
        if primary_prop.property_id:
            prop = get_property_by_id(db, primary_prop.property_id, try_year)
            if prop:
                return prop
    
    return None


def set_property_assignment(
    db: Session, property_raw_hash: str | None, property_id: str | None, assigned: bool = True
):
    """Set property assignment status."""
    update_stmt = None
    if property_raw_hash:
        update_stmt = (
            update(PropertyView)
            .where(PropertyView.raw_hash == property_raw_hash)
            .values(assigned_to_lead=assigned)
        )
    elif property_id:
        update_stmt = (
            update(PropertyView)
            .where(PropertyView.propertyid == property_id)
            .values(assigned_to_lead=assigned)
        )

    if update_stmt is not None:
        db.execute(update_stmt)


def mark_property_assigned(db: Session, property_raw_hash: str | None, property_id: str | None):
    """Mark a property as assigned to a lead."""
    set_property_assignment(db, property_raw_hash, property_id, True)


def unmark_property_if_unused(db: Session, property_raw_hash: str | None, property_id: str | None):
    """Unmark a property if it's no longer used by any lead."""
    if property_raw_hash:
        still_used = db.scalar(
            select(LeadProperty.id)
            .where(LeadProperty.property_raw_hash == property_raw_hash)
            .limit(1)
        )
        if not still_used:
            set_property_assignment(db, property_raw_hash, None, False)
            return

    if property_id:
        still_used = db.scalar(
            select(LeadProperty.id)
            .where(LeadProperty.property_id == property_id)
            .limit(1)
        )
        if not still_used:
            set_property_assignment(db, None, property_id, False)


def sync_existing_property_assignments():
    """Sync property assignments from existing leads."""
    from db import SessionLocal
    
    db = SessionLocal()
    try:
        # Get all property_raw_hashes from LeadProperty table
        raw_hashes = {
            value
            for value in db.scalars(
                select(LeadProperty.property_raw_hash).where(
                    LeadProperty.property_raw_hash.is_not(None)
                )
            ).all()
            if value
        }
        if raw_hashes:
            db.execute(
                update(PropertyView)
                .where(PropertyView.raw_hash.in_(tuple(raw_hashes)))
                .values(assigned_to_lead=True)
            )

        # Get all property_ids from LeadProperty table
        property_ids = {
            value
            for value in db.scalars(
                select(LeadProperty.property_id).where(
                    LeadProperty.property_id.is_not(None)
                )
            ).all()
            if value
        }
        if property_ids:
            db.execute(
                update(PropertyView)
                .where(PropertyView.propertyid.in_(tuple(property_ids)))
                .values(assigned_to_lead=True)
            )

        if raw_hashes or property_ids:
            db.commit()
    finally:
        db.close()


def property_navigation_info(db: Session, raw_hash: str, year: str | None = None):
    """Get property navigation info for the specified year's table."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = get_property_table_for_year(year)
    property_ordering = (prop_table.c.propertyamount.desc(), prop_table.c.row_hash.asc())
    
    ranked = (
        select(
            prop_table.c.row_hash.label("raw_hash"),
            func.row_number().over(order_by=property_ordering).label("order_id"),
            func.lag(prop_table.c.row_hash).over(order_by=property_ordering).label("prev_hash"),
            func.lead(prop_table.c.row_hash).over(order_by=property_ordering).label("next_hash"),
        )
        .where(prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT)
        .subquery()
    )
    nav_row = db.execute(
        select(
            ranked.c.order_id,
            ranked.c.prev_hash,
            ranked.c.next_hash,
        ).where(ranked.c.raw_hash == raw_hash)
    ).one_or_none()
    if not nav_row:
        return {
            "order_id": None,
            "prev_order_id": None,
            "next_order_id": None,
            "prev_hash": None,
            "next_hash": None,
        }

    order_id = nav_row.order_id
    prev_hash = nav_row.prev_hash
    next_hash = nav_row.next_hash

    return {
        "order_id": order_id,
        "prev_order_id": order_id - 1 if prev_hash else None,
        "next_order_id": order_id + 1 if next_hash else None,
        "prev_hash": prev_hash,
        "next_hash": next_hash,
    }


def find_related_properties_by_owner_name(
    db: Session, 
    owner_name: str, 
    exclude_lead_id: int | None = None,
    year: str | None = None
) -> list[dict]:
    """
    Find properties with the same owner name (normalized) that are not already assigned to a lead.
    
    Args:
        db: Database session
        owner_name: Owner name to search for
        exclude_lead_id: Optional lead ID to exclude from "already assigned" check (for existing leads)
        year: Year for property table (defaults to DEFAULT_YEAR)
    
    Returns:
        List of property dictionaries that match the owner name and are not assigned
    """
    if not year:
        year = DEFAULT_YEAR
    
    from utils.name_utils import normalize_name
    
    # Normalize the owner name for comparison
    normalized_owner_name = normalize_name(owner_name).lower().strip()
    if not normalized_owner_name:
        return []
    
    prop_table = get_property_table_for_year(year)
    
    # Get all properties with matching owner name (case-insensitive, normalized)
    # NOTE: We do NOT apply the 10k amount filter here - we want to show ALL properties
    # with the same owner name so users can choose which ones to add
    all_props = db.execute(
        select(
            prop_table.c.row_hash.label("raw_hash"),
            prop_table.c.propertyid.label("propertyid"),
            prop_table.c.ownername.label("ownername"),
            prop_table.c.propertyamount.label("propertyamount"),
            prop_table.c.holdername.label("holdername"),
            prop_table.c.owneraddress1.label("owneraddress1"),
            prop_table.c.owneraddress2.label("owneraddress2"),
            prop_table.c.owneraddress3.label("owneraddress3"),
            prop_table.c.ownercity.label("ownercity"),
            prop_table.c.ownerstate.label("ownerstate"),
            prop_table.c.ownerzipcode.label("ownerzipcode"),
            prop_table.c.ownerrelation.label("ownerrelation"),
            prop_table.c.lastactivitydate.label("lastactivitydate"),
            prop_table.c.reportyear.label("reportyear"),
            prop_table.c.propertytypedescription.label("propertytypedescription"),
        )
        .where(prop_table.c.ownername.is_not(None))
    ).all()
    
    # Get all property hashes that are assigned to any lead
    all_assigned = db.scalars(
        select(LeadProperty.property_raw_hash).where(LeadProperty.property_raw_hash.is_not(None))
    ).all()
    assigned_hashes = set(all_assigned)
    
    # If exclude_lead_id is provided, get properties already in that lead to exclude them
    if exclude_lead_id:
        assigned_to_this_lead = db.scalars(
            select(LeadProperty.property_raw_hash).where(LeadProperty.lead_id == exclude_lead_id)
        ).all()
        assigned_to_this_lead_set = set(assigned_to_this_lead)
    else:
        assigned_to_this_lead_set = set()
    
    # Filter properties by normalized owner name and exclude already assigned
    related_props = []
    for prop_row in all_props:
        prop_dict = dict(prop_row._mapping)
        prop_owner_name = (prop_dict.get("ownername") or "").strip()
        normalized_prop_owner = normalize_name(prop_owner_name).lower().strip()
        
        # Match if normalized names are the same
        if normalized_prop_owner == normalized_owner_name:
            raw_hash = prop_dict.get("raw_hash")
            # Exclude if already assigned to another lead
            if raw_hash and raw_hash in assigned_hashes:
                # Only include if it's assigned to the current lead (we want to show it)
                if not (exclude_lead_id and raw_hash in assigned_to_this_lead_set):
                    continue  # Skip - assigned to another lead
            
            # Exclude if already in current lead (for existing leads)
            if exclude_lead_id and raw_hash and raw_hash in assigned_to_this_lead_set:
                continue  # Skip - already in this lead
            
            related_props.append(prop_dict)
    
    return related_props


def build_gpt_payload(lead: BusinessLead, prop: dict) -> dict:
    """Build GPT payload from lead and property dict."""
    report_year_value = None
    if prop.get("reportyear"):
        try:
            report_year_value = int(str(prop.get("reportyear")))
        except (TypeError, ValueError):
            report_year_value = None

    return {
        "business_name": lead.owner_name or prop.get("ownername") or "",
        "property_state": prop.get("ownerstate") or "",
        "holder_name_on_record": prop.get("holdername") or "",
        "last_activity_date": prop.get("lastactivitydate") or "",
        "property_report_year": report_year_value,
    }

