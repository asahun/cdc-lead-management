"""
Data normalization utilities.
"""

from fastapi import HTTPException

from models import (
    OwnerType,
    BusinessOwnerStatus,
    OwnerSize,
    IndividualOwnerStatus,
)


def normalize_owner_fields(
    owner_type: OwnerType,
    business_owner_status: BusinessOwnerStatus | None,
    owner_size: OwnerSize | None,
    new_business_name: str | None,
    individual_owner_status: IndividualOwnerStatus | None,
    validate: bool = True
) -> dict:
    """
    Normalize owner-related fields based on owner_type.
    Returns dict with normalized values.
    """
    if owner_type == OwnerType.business:
        normalized = {
            "individual_owner_status": None,
            "business_owner_status": business_owner_status or BusinessOwnerStatus.active,
            "owner_size": owner_size or OwnerSize.corporate,
        }
        # Handle new_business_name validation
        if normalized["business_owner_status"] in (
            BusinessOwnerStatus.acquired_or_merged,
            BusinessOwnerStatus.active_renamed,
        ):
            if validate and (not new_business_name or not new_business_name.strip()):
                raise HTTPException(
                    status_code=400,
                    detail="New owner name is required when status is acquired_or_merged or active_renamed."
                )
            normalized["new_business_name"] = new_business_name
        else:
            normalized["new_business_name"] = None
    else:
        # Individual logic
        normalized = {
            "business_owner_status": None,
            "owner_size": None,
            "new_business_name": None,
            "individual_owner_status": individual_owner_status or IndividualOwnerStatus.alive,
        }
    
    return normalized

