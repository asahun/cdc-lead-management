"""
Print log helpers - shared across routers.
"""

from typing import Any
from sqlalchemy.orm import Session
from sqlalchemy import select

from models import PrintLog


def get_print_logs_for_lead(db: Session, lead_id: int):
    """
    Get all print logs for a lead, ordered by printed_at descending.
    """
    result = db.execute(
        select(PrintLog)
        .where(PrintLog.lead_id == lead_id)
        .order_by(PrintLog.printed_at.desc())
    )
    return result.scalars().all()


def serialize_print_log(log: PrintLog) -> dict[str, Any]:
    """
    Serialize a PrintLog object to a dictionary for JSON responses.
    """
    contact = log.contact
    address_lines: list[str] = []
    if contact:
        if contact.address_street:
            address_lines.append(contact.address_street.strip())
        city = (contact.address_city or "").strip()
        state = (contact.address_state or "").strip()
        zipcode = (contact.address_zipcode or "").strip()
        if city or state:
            line = ", ".join(part for part in (city, state) if part)
            if zipcode:
                line = f"{line} {zipcode}".strip()
            address_lines.append(line)
        elif zipcode:
            address_lines.append(zipcode)

    return {
        "id": log.id,
        "leadId": log.lead_id,
        "contactId": log.contact_id,
        "contactName": contact.contact_name if contact else "",
        "contactTitle": contact.title if contact else "",
        "addressLines": [line for line in address_lines if line],
        "filename": log.filename,
        "filePath": log.file_path,
        "printedAt": log.printed_at.isoformat() if log.printed_at else None,
        "mailed": log.mailed,
        "mailedAt": log.mailed_at.isoformat() if log.mailed_at else None,
        "attemptId": log.attempt_id,
    }

