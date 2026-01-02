"""
Property service - handles all property-related business logic.
"""

from decimal import Decimal
from typing import Optional
import re

from sqlalchemy.orm import Session
from sqlalchemy import select, func, update, cast, String, Integer, Table, MetaData, inspect, exists, and_, or_

from db import engine
from models import PropertyView, Lead, LeadProperty
from helpers.property_helpers import get_primary_property

# Constants
PROPERTY_MIN_AMOUNT = Decimal("10000")
DEFAULT_YEAR = "2025"

# Cache for available years
_YEAR_TABLES_LIST: Optional[list[str]] = None


# ============================================================================
# Property Owner Name Normalization Functions
# ============================================================================
# These functions handle normalization of property owner names (business names)
# for matching and searching purposes.

def normalize_property_owner_name(name: str) -> str:
    """
    Normalize property owner name (business name) for matching:
    - lowercase
    - trim
    - remove punctuation (commas/periods)
    - collapse whitespace
    - remove common legal suffix tokens (inc, llc, ltd, corp, company, co, incorporated, corporation)
    
    This is used for matching property owner names across different formats.
    """
    if not name:
        return ""
    normalized = name.lower().strip()
    # Remove punctuation
    normalized = re.sub(r'[,\.;:!?]', '', normalized)
    # Remove common legal suffix tokens
    normalized = re.sub(
        r'\b(inc|incorporated|corp|corporation|llc|l\.l\.c\.|ltd|limited|co|company|lp|l\.p\.|llp|l\.l\.p\.)\b',
        '',
        normalized,
        flags=re.IGNORECASE,
    )
    # Collapse whitespace
    normalized = ' '.join(normalized.split())
    return normalized


def reorder_first_token_to_end(normalized: str) -> str:
    """
    Reorder tokens: move first token to end.
    
    Used for flipped name matching (e.g., "ABC Corp LLC" -> "Corp LLC ABC").
    
    Examples:
        "abc corp llc" -> "corp llc abc"
        "xyz" -> "xyz" (single token, unchanged)
        "a b c" -> "b c a"
    """
    if not normalized:
        return normalized
    
    tokens = normalized.split()
    if len(tokens) < 2:
        return normalized
    
    # Move first token to end
    return ' '.join(tokens[1:] + [tokens[0]])


def suffix_or_special_present(name: str) -> bool:
    """
    Detect if the original name contains legal suffix tokens or special characters.
    
    Used to determine if flip matching is allowed (flip only works for 3-token names
    without suffixes or special characters).
    """
    if not name:
        return False
    lowered = name.lower()
    has_special = bool(re.search(r"[^\w\s]", lowered))
    suffix_pattern = r"\b(inc|inc\.|incorporated|corp|corporation|llc|l\.l\.c\.|ltd|limited|co|company|lp|l\.p\.|llp|l\.l\.p\.)\b"
    has_suffix = bool(re.search(suffix_pattern, lowered))
    return has_special or has_suffix


def flip_allowed(normalized_name: str, original_name: str) -> bool:
    """
    Check if flip matching is allowed for a name.
    
    Flip is only allowed for names with exactly 3 tokens and no suffix/special characters.
    
    Args:
        normalized_name: The normalized name (without suffixes)
        original_name: The original name (to check for suffixes/special chars)
    
    Returns:
        True if flip matching is allowed, False otherwise
    """
    tokens = normalized_name.split()
    return len(tokens) == 3 and not suffix_or_special_present(original_name)


def get_available_years(db: Session) -> list[str]:
    """Discover available years from the unified property table."""
    global _YEAR_TABLES_LIST
    
    if _YEAR_TABLES_LIST is not None:
        return _YEAR_TABLES_LIST
    
    # Query distinct years from the unified property table
    years = db.scalars(
        select(PropertyView.reportyear)
        .distinct()
        .where(PropertyView.reportyear.is_not(None))
        .order_by(PropertyView.reportyear.desc())
    ).all()
    
    # Convert to strings and sort descending (newest first)
    year_tables = [str(year) for year in years if year is not None]
    year_tables.sort(reverse=True, key=lambda x: int(x) if x.isdigit() else 0)
    _YEAR_TABLES_LIST = year_tables
    return year_tables


def get_property_table_for_year(year: str | None = None) -> Table:
    """Get SQLAlchemy Table object for the unified property table.
    
    Note: The table is unified now, but we still filter by reportyear column.
    This function returns the table and callers should add year filtering.
    """
    if not year:
        year = DEFAULT_YEAR
    
    # Return the unified property table (PropertyView maps to 'property' table)
    return PropertyView.__table__


def build_property_select(prop_table, year: str | None = None):
    """Build the common SELECT statement for property lookups."""
    if not year:
        year = DEFAULT_YEAR
    
    stmt = select(
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
    ).where(
        prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT,
        cast(prop_table.c.reportyear, Integer) == int(year)
    )
    return stmt


def get_property_by_id(db: Session, property_id: str, year: str | None = None) -> dict | None:
    """Get property by ID from the unified property table. Returns dict with property data."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = get_property_table_for_year(year)
    
    # Build select without amount filter for single property lookup, but filter by year
    result = db.execute(
        select(
            prop_table.c.row_hash.label("raw_hash"),
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
        )
        .where(
            cast(prop_table.c.propertyid, String) == property_id,  # Cast to match text type
            cast(prop_table.c.reportyear, Integer) == int(year)
        )
        .limit(1)
    ).first()
    
    if result:
        return dict(result._mapping)
    return None


def get_property_by_raw_hash(db: Session, raw_hash: str, year: str | None = None) -> dict | None:
    """Get property by raw hash from the unified property table. Returns dict with property data."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = get_property_table_for_year(year)
    
    # Build select without amount filter for single property lookup, but filter by year
    # Note: raw_hash is unique across all years, but we still filter by year for consistency
    result = db.execute(
        select(
            prop_table.c.row_hash.label("raw_hash"),
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
        )
        .where(
            prop_table.c.row_hash == raw_hash,  # Database column is "row_hash"
            cast(prop_table.c.reportyear, Integer) == int(year)
        )
        .limit(1)
    ).first()
    
    if result:
        return dict(result._mapping)
    return None


def get_raw_hash_for_order(db: Session, order_id: int, year: str | None = None) -> str | None:
    """Get raw hash for a property by order ID from the unified property table."""
    if not year:
        year = DEFAULT_YEAR
    
    prop_table = get_property_table_for_year(year)
    property_ordering = (prop_table.c.propertyamount.desc(), prop_table.c.row_hash.asc())
    
    ranked = (
        select(
            prop_table.c.row_hash.label("raw_hash"),  # Database column is "row_hash", label as "raw_hash"
            func.row_number().over(order_by=property_ordering).label("order_id"),
        )
        .where(
            prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT,
            cast(prop_table.c.reportyear, Integer) == int(year)
        )
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


def get_property_details_for_lead(db: Session, lead: Lead, year: str | None = None) -> dict | None:
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
    """Get property navigation info for the unified property table."""
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
        .where(
            prop_table.c.propertyamount >= PROPERTY_MIN_AMOUNT,
            cast(prop_table.c.reportyear, Integer) == int(year)
        )
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
    year: str | None = None,
    flip: bool = False
) -> list[dict]:
    """
    Find properties with the same owner name (normalized for business names) that are not already assigned to a lead.
    
    Args:
        db: Database session
        owner_name: Owner name to search for (business name)
        exclude_lead_id: Optional lead ID to exclude from "already assigned" check (for existing leads)
        year: Year for property table (defaults to DEFAULT_YEAR)
        flip: If True, also search for flipped names (first token moved to end)
    
    Returns:
        List of property dictionaries that match the owner name and are not assigned
    """
    if not year:
        year = DEFAULT_YEAR
    
    # Normalize the owner name using property owner name normalization (removes suffixes like inc, corp, llc)
    normalized_owner_name = normalize_property_owner_name(owner_name)
    if not normalized_owner_name:
        return []
    
    # If flip is enabled, check if flip is allowed and prepare flipped name
    normalized_names_to_match = [normalized_owner_name]
    if flip:
        # Only flip if allowed (3 tokens, no suffix/special chars)
        if flip_allowed(normalized_owner_name, owner_name):
            flipped_name = reorder_first_token_to_end(normalized_owner_name)
            if flipped_name and flipped_name != normalized_owner_name:
                normalized_names_to_match.append(flipped_name)
    
    prop_table = get_property_table_for_year(year)
    
    # Build base query with SQL-level filtering to exclude assigned properties
    # This is much more efficient than loading all assigned hashes into memory
    base_query = select(
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
    ).where(
        prop_table.c.ownername.is_not(None),
        cast(prop_table.c.reportyear, Integer) == int(year),
        # Exclude properties already assigned to OTHER leads (not the current one)
        ~exists(
            select(1).where(
                LeadProperty.property_raw_hash == prop_table.c.row_hash,
                # If exclude_lead_id is provided, allow properties assigned to that lead
                # (we'll exclude them separately if needed)
                (LeadProperty.lead_id != exclude_lead_id) if exclude_lead_id else True
            )
        )
    )
    
    # If exclude_lead_id is provided, also exclude properties already in that lead
    if exclude_lead_id:
        base_query = base_query.where(
            ~exists(
                select(1).where(
                    LeadProperty.property_raw_hash == prop_table.c.row_hash,
                    LeadProperty.lead_id == exclude_lead_id
                )
            )
        )
    
    # Execute query to get candidate properties
    # We use a broad ILIKE pattern first, then do exact normalized matching in Python
    # since business name normalization can't be done purely in SQL
    # Use ILIKE directly (without cast/lower) to allow GIN index usage
    ilike_patterns = [f"%{name}%" for name in normalized_names_to_match]
    ilike_conditions = [
        prop_table.c.ownername.ilike(pattern)
        for pattern in ilike_patterns
    ]
    # Use OR to match any of the patterns (original or flipped)
    base_query = base_query.where(or_(*ilike_conditions))
    
    filtered_props = db.execute(base_query).all()
    
    # Filter properties by exact normalized owner name matching (property owner name normalization)
    # This must be done in Python since normalization removes suffixes and can't be done in SQL
    related_props = []
    for prop_row in filtered_props:
        prop_dict = dict(prop_row._mapping)
        prop_owner_name = (prop_dict.get("ownername") or "").strip()
        normalized_prop_owner = normalize_property_owner_name(prop_owner_name)
        
        # Match if normalized names are the same (or flipped if enabled)
        if normalized_prop_owner in normalized_names_to_match:
            related_props.append(prop_dict)
    
    return related_props


def _is_placeholder_value(value: str) -> bool:
    """
    Check if an address field value is a placeholder/invalid value.
    
    Returns True for values like 'UNKNOWN', '00000', 'N/A', etc.
    """
    if not value:
        return True
    
    normalized = value.strip().upper()
    
    # Common placeholder patterns
    placeholders = {
        'UNKNOWN',
        'N/A',
        'NA',
        'NULL',
        'NONE',
        '',
    }
    
    if normalized in placeholders:
        return True
    
    # All zeros (for zipcodes: 00000, 00000-0000, etc.)
    if normalized.replace('-', '').replace(' ', '').isdigit():
        if all(c == '0' for c in normalized.replace('-', '').replace(' ', '')):
            return True
    
    return False


def format_property_address(prop: dict) -> str | None:
    """
    Format property address fields into a single combined string.
    
    Combines owneraddress1, owneraddress2, owneraddress3, ownercity, ownerstate, ownerzipcode
    into a formatted address string. Filters out placeholder values like 'UNKNOWN', '00000', etc.
    
    Format: "address1, address2, address3, city, state zipcode"
    
    Args:
        prop: Property dictionary with address fields
        
    Returns:
        Formatted address string, or None if no valid address fields are present
    """
    address_parts = []
    for field in ["owneraddress1", "owneraddress2", "owneraddress3"]:
        value = prop.get(field)
        if value and not _is_placeholder_value(str(value)):
            address_parts.append(str(value).strip())
    
    city_state_zip = []
    city = prop.get("ownercity")
    state = prop.get("ownerstate")
    zipcode = prop.get("ownerzipcode")
    
    if city and not _is_placeholder_value(str(city)):
        city_state_zip.append(str(city).strip())
    if state and not _is_placeholder_value(str(state)):
        city_state_zip.append(str(state).strip())
    if zipcode and not _is_placeholder_value(str(zipcode)):
        city_state_zip.append(str(zipcode).strip())
    
    # Combine: address parts with commas, then city/state/zip with commas, space before zip if state exists
    formatted_address = ""
    if address_parts:
        formatted_address = ", ".join(address_parts)
    if city_state_zip:
        if formatted_address:
            formatted_address += ", "
        # Format city, state zipcode (space between state and zip)
        if len(city_state_zip) == 3:
            formatted_address += f"{city_state_zip[0]}, {city_state_zip[1]} {city_state_zip[2]}"
        elif len(city_state_zip) == 2:
            formatted_address += f"{city_state_zip[0]}, {city_state_zip[1]}"
        else:
            formatted_address += city_state_zip[0]
    
    return formatted_address if formatted_address else None


def build_gpt_payload(lead: Lead, prop: dict) -> dict:
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
        "city": prop.get("ownercity") or None,
    }

