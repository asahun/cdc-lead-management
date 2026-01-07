from typing import Any

import requests

from ai_agent.settings import Settings


def _normalize(value: str) -> str:
    return " ".join((value or "").lower().strip().split())


def _name_similarity(a: str, b: str) -> float:
    a_tokens = set(_normalize(a).split())
    b_tokens = set(_normalize(b).split())
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    return overlap / max(len(a_tokens), len(b_tokens))


def lookup_place(
    business_name: str,
    settings: Settings,
    city: str | None = None,
    state: str | None = None,
) -> dict[str, Any] | None:
    if not settings.google_places_api_key:
        return None

    text_search_url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": (
            "places.id,"
            "places.displayName,"
            "places.formattedAddress,"
            "places.businessStatus,"
            "places.nationalPhoneNumber,"
            "places.websiteUri,"
            "places.primaryType,"
            "places.types"
        ),
    }

    try:
        query_parts = [business_name.strip()]
        if city:
            query_parts.append(city.strip())
        if state:
            query_parts.append(state.strip())
        query = " ".join(part for part in query_parts if part)
        resp = requests.post(
            text_search_url,
            headers=headers,
            json={"textQuery": query, "pageSize": 5},
            timeout=settings.google_places_timeout,
        )
        resp.raise_for_status()
        places = (resp.json() or {}).get("places", [])
        if not places:
            return None
    except Exception:
        return None

    best = None
    best_similarity = -1.0
    for place in places:
        display_name = place.get("displayName")
        if isinstance(display_name, dict):
            display_name = display_name.get("text")
        similarity = _name_similarity(business_name, display_name or "")
        if similarity > best_similarity:
            best_similarity = similarity
            best = place

    if not best:
        return None

    display_name = best.get("displayName")
    if isinstance(display_name, dict):
        display_name = display_name.get("text")

    return {
        "place_id": best.get("id"),
        "display_name": display_name,
        "formatted_address": best.get("formattedAddress"),
        "business_status": best.get("businessStatus"),
        "national_phone": best.get("nationalPhoneNumber"),
        "website_uri": best.get("websiteUri"),
        "primary_type": best.get("primaryType"),
        "types": best.get("types") or [],
        "name_similarity": round(best_similarity, 3),
    }
