from __future__ import annotations

import re
from typing import Tuple

SPACE_RE = re.compile(r"\s+")
TRIM_CHARS = " \t\r\n,."


def _capitalize_segment(segment: str) -> str:
    segment = segment.strip()
    if not segment:
        return ""
    return segment[0].upper() + segment[1:].lower()


def _normalize_token(token: str) -> str:
    token = (token or "").strip(TRIM_CHARS)
    if not token:
        return ""

    lowered = token.lower()
    hyphen_parts = lowered.split("-")
    normalized_hyphen_parts = []

    for hyphen_part in hyphen_parts:
        apostrophe_parts = hyphen_part.split("'")
        normalized_apostrophe_parts = [_capitalize_segment(part) for part in apostrophe_parts]
        normalized_hyphen_parts.append("'".join(normalized_apostrophe_parts))

    return "-".join(normalized_hyphen_parts)


def normalize_name(value: str | None) -> str:
    """
    Normalize a first/last/full name so each component has leading capitalization.
    """
    if not value:
        return ""

    parts = SPACE_RE.split(value.strip())
    normalized_parts = [_normalize_token(part) for part in parts if part]
    return " ".join(part for part in normalized_parts if part)


def split_name(value: str | None) -> Tuple[str, str]:
    """
    Split a full name into normalized first and remaining parts.
    """
    normalized = normalize_name(value)
    if not normalized:
        return "", ""

    parts = normalized.split(" ")
    first = parts[0]
    last = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first, last


def format_first_name(value: str | None) -> str:
    first, _ = split_name(value)
    return first


def format_full_name(first: str | None, last: str | None) -> str:
    formatted_first = normalize_name(first)
    formatted_last = normalize_name(last)
    if formatted_first and formatted_last:
        return f"{formatted_first} {formatted_last}"
    return formatted_first or formatted_last

