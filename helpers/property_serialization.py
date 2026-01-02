from decimal import Decimal

from services.property_service import format_property_address


def normalize_property_amount(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def related_property_payload(prop: dict, include_address: bool = False) -> dict:
    payload = {
        "property_id": str(prop.get("propertyid") or ""),
        "property_raw_hash": str(prop.get("raw_hash") or ""),
        "property_amount": normalize_property_amount(prop.get("propertyamount")),
        "holder_name": str(prop.get("holdername") or ""),
        "owner_name": str(prop.get("ownername") or ""),
        "reportyear": str(prop.get("reportyear") or "") if prop.get("reportyear") else None,
    }
    if include_address:
        payload["address"] = format_property_address(prop) or None
    return payload
