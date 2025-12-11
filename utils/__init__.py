"""
Utility modules for the lead management application.
"""

# Re-export commonly used utilities
from utils.formatters import format_currency
from utils.validators import (
    get_lead_or_404,
    get_contact_or_404,
    normalize_contact_id,
    is_lead_editable,
)
from utils.normalizers import normalize_owner_fields
from utils.html_processing import (
    plain_text_to_html,
    looks_like_html,
    extract_body_fragment,
    strip_tags_to_text,
    prepare_script_content,
)
from utils.datetime_helpers import previous_monday_cutoff, APP_TIMEZONE
from utils.attempt_helpers import get_next_attempt_number

__all__ = [
    "format_currency",
    "get_lead_or_404",
    "get_contact_or_404",
    "normalize_contact_id",
    "is_lead_editable",
    "normalize_owner_fields",
    "plain_text_to_html",
    "looks_like_html",
    "extract_body_fragment",
    "strip_tags_to_text",
    "prepare_script_content",
    "previous_monday_cutoff",
    "APP_TIMEZONE",
    "get_next_attempt_number",
]
