import re
from dataclasses import dataclass
from typing import Any


GOV_KEYWORDS = [
    "county",
    "city",
    "state",
    "department",
    "dept",
    "board",
    "authority",
    "commission",
    "district",
    "school",
    "schools",
    "public",
    "government",
    "municipal",
    "township",
]

FEDERAL_KEYWORDS = [
    "agency",
    "department",
    "bureau",
    "administration",
    "office of",
]

STATE_LOCAL_CIVIC_TOKENS = [
    "clerk",
    "treasurer",
    "tax commissioner",
    "assessor",
    "sheriff",
    "courthouse",
    "court",
    "police",
    "fire",
    "public works",
    "water",
    "sanitation",
    "board of",
    "commission",
    "authority",
    "department",
    "dept",
    "office",
]

ESTATE_KEYWORDS = [
    "estate of",
    "trust",
    "revocable",
    "living trust",
    "irrevocable",
]

NONPROFIT_KEYWORDS = [
    "association",
    "foundation",
    "church",
    "ministry",
    "nonprofit",
    "society",
    "club",
]

RELIGIOUS_KEYWORDS = [
    "church",
    "ministry",
    "apostolic",
    "temple",
    "mosque",
    "synagogue",
    "ministries",
]

ANTI_GOV_TOKENS = [
    "foundation",
    "charity",
    "association",
    "hope",
    "truth",
    "mission",
    "ministries",
]

SUFFIX_KEYWORDS = [
    "llc",
    "l.l.c",
    "inc",
    "inc.",
    "corp",
    "corp.",
    "corporation",
    "co",
    "co.",
    "company",
    "lp",
    "l.p",
    "llp",
    "l.l.p",
    "pllc",
    "p.l.l.c",
]


@dataclass
class CandidateScore:
    record: dict[str, Any]
    score: float
    reasons: list[str]
    components: dict[str, float]
    location_quality: str


@dataclass
class EntityTypeDecision:
    entity_type: str
    confidence: float
    reason_code: str
    needs_review: bool


def _normalize(value: str) -> str:
    lowered = (value or "").lower().strip()
    lowered = re.sub(r"[\.,;:!?]", "", lowered)
    return " ".join(lowered.split())


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _collect_context_tokens(holder_name: str | None, holder_address: dict[str, Any] | None) -> str:
    parts = [holder_name or ""]
    if holder_address:
        parts.extend(
            [
                holder_address.get("street") or "",
                holder_address.get("street2") or "",
                holder_address.get("street3") or "",
                holder_address.get("city") or "",
                holder_address.get("state") or "",
                holder_address.get("zip") or "",
            ]
        )
    return _normalize(" ".join(part for part in parts if part))


def _is_acronym_only(owner_name: str) -> bool:
    stripped = re.sub(r"[^A-Za-z0-9]", "", owner_name or "")
    if not stripped:
        return False
    return stripped.isupper() and 2 <= len(stripped) <= 6


def _has_business_suffix(text: str) -> bool:
    tokens = _normalize(text).split()
    return any(token in SUFFIX_KEYWORDS for token in tokens)


def _has_civic_office_tokens(text: str) -> bool:
    return any(token in text for token in STATE_LOCAL_CIVIC_TOKENS)


def _place_plausibility_score(place_phrase: str) -> int:
    tokens = place_phrase.split()
    score = 0
    if 1 <= len(tokens) <= 3:
        score += 30
    elif len(tokens) == 4:
        score += 10

    if any(token in place_phrase for token in RELIGIOUS_KEYWORDS + ANTI_GOV_TOKENS):
        score -= 60

    return score


def classify_entity_type(
    owner_name: str,
    holder_name: str | None = None,
    holder_address: dict[str, Any] | None = None,
) -> EntityTypeDecision:
    owner_text = _normalize(owner_name or "")
    context_text = _collect_context_tokens(holder_name, holder_address)

    if _contains_keyword(owner_text, RELIGIOUS_KEYWORDS):
        return EntityTypeDecision("nonprofit", 0.75, "NONPROFIT_RELIGIOUS_PATTERN", False)

    if _contains_keyword(owner_text, NONPROFIT_KEYWORDS):
        return EntityTypeDecision("nonprofit", 0.7, "NONPROFIT_KEYWORD_PATTERN", False)

    if _contains_keyword(owner_text, ESTATE_KEYWORDS):
        return EntityTypeDecision("estate_trust", 0.8, "ESTATE_TRUST_PATTERN", False)

    if _is_acronym_only(owner_name) and not _contains_keyword(owner_text, GOV_KEYWORDS):
        return EntityTypeDecision("ambiguous", 0.4, "ACRONYM_UNRESOLVED", True)

    federal_trigger = (
        ("united states" in owner_text or "u s" in owner_text or "u.s" in owner_text or "us " in owner_text)
        and any(token in owner_text for token in FEDERAL_KEYWORDS)
    )
    if federal_trigger:
        return EntityTypeDecision("government_federal", 0.9, "GOV_FEDERAL_STRONG_KEYWORD", False)

    if _has_civic_office_tokens(owner_text):
        return EntityTypeDecision("government_state_local", 0.9, "GOV_CIVIC_OFFICE_PATTERN", False)

    if re.search(r"\bcounty\b", owner_text) and not _has_business_suffix(owner_text):
        if owner_text.endswith(" county") or re.search(r"\bcounty\b\s*(,|$)", owner_text) or owner_text.startswith("county of "):
            return EntityTypeDecision("government_state_local", 0.9, "GOV_COUNTY_NAME_PATTERN", False)
        commercial_terms = ["county line", "county market", "county auto", "county sales", "county bank"]
        if any(term in owner_text for term in commercial_terms):
            return EntityTypeDecision("ambiguous", 0.6, "GOV_COUNTY_NAME_WEAK", True)
        return EntityTypeDecision("ambiguous", 0.6, "GOV_COUNTY_NAME_WEAK", True)

    if owner_text.startswith("city of ") or owner_text.startswith("county of "):
        if _has_business_suffix(owner_text):
            return EntityTypeDecision("ambiguous", 0.5, "GOV_AMBIGUOUS_NEEDS_REVIEW", True)
        place_phrase = " ".join(owner_text.split()[2:5])
        score = _place_plausibility_score(place_phrase)
        if score >= 60:
            return EntityTypeDecision("government_state_local", 0.8, "GOV_CITY_COUNTY_PLAUSIBLE", False)
        return EntityTypeDecision("ambiguous", 0.5, "GOV_AMBIGUOUS_NEEDS_REVIEW", True)

    if _contains_keyword(context_text, GOV_KEYWORDS):
        return EntityTypeDecision("ambiguous", 0.5, "GOV_AMBIGUOUS_NEEDS_REVIEW", True)

    return EntityTypeDecision("business", 0.6, "BUSINESS_DEFAULT", False)


def _strip_suffix_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token not in SUFFIX_KEYWORDS]


def _token_overlap(a: str, b: str) -> float:
    a_tokens = set(_strip_suffix_tokens(_normalize(a).split()))
    b_tokens = set(_strip_suffix_tokens(_normalize(b).split()))
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(b_tokens)


def _location_quality(holder_address: dict[str, Any]) -> str:
    if not holder_address:
        return "LOW"
    has_street = bool(_normalize(holder_address.get("street") or ""))
    has_city = bool(_normalize(holder_address.get("city") or ""))
    has_zip = bool(_normalize(holder_address.get("zip") or ""))
    if has_street and (has_city or has_zip):
        return "HIGH"
    if has_city or has_zip:
        return "MEDIUM"
    return "LOW"


def location_evidence_quality(holder_address: dict[str, Any] | None) -> str:
    return _location_quality(holder_address or {})


def location_quality_with_source(
    holder_address: dict[str, Any] | None,
    address_source: str | None,
) -> str:
    quality = _location_quality(holder_address or {})
    if address_source == "property_mailing" and quality == "HIGH":
        return "MEDIUM"
    return quality


def strong_name_match(owner_name: str, candidate_name: str) -> bool:
    owner_norm = _normalize(owner_name)
    candidate_norm = _normalize(candidate_name)
    if owner_norm == candidate_norm:
        return True
    overlap = _token_overlap(owner_name, candidate_name)
    owner_suffix = _extract_suffix(owner_name)
    candidate_suffix = _extract_suffix(candidate_name)
    if owner_suffix and candidate_suffix and owner_suffix != candidate_suffix:
        return False
    return overlap >= 0.9


def _extract_place_token(owner_name: str) -> str | None:
    tokens = _normalize(owner_name).split()
    tokens = [t for t in tokens if t not in {"county", "city", "of"}]
    return tokens[0] if tokens else None


def government_validation_from_places(
    owner_name: str,
    places_profile: dict[str, Any] | None,
) -> EntityTypeDecision | None:
    if not places_profile:
        return None
    types = places_profile.get("types") or []
    primary_type = places_profile.get("primary_type") or ""
    website_uri = (places_profile.get("website_uri") or "").lower()
    display_name = places_profile.get("display_name") or ""
    name_similarity = float(places_profile.get("name_similarity") or 0.0)

    if name_similarity < 0.75:
        return None

    if "county" in _normalize(owner_name):
        token = _extract_place_token(owner_name)
        if token and token not in _normalize(display_name):
            return None

    gov_types = {
        "government_office",
        "local_government_office",
        "city_hall",
        "courthouse",
        "embassy",
        "police",
        "fire_station",
        "post_office",
    }

    if primary_type in gov_types or any(t in gov_types for t in types):
        return EntityTypeDecision("government_state_local", 0.9, "GOV_VALIDATED_BY_PLACES", False)

    if website_uri.endswith(".gov") or website_uri.endswith(".mil"):
        if ".ga.gov" in website_uri or "georgia.gov" in website_uri:
            return EntityTypeDecision("government_state_local", 0.8, "GOV_VALIDATED_BY_GOV_DOMAIN", False)
        return EntityTypeDecision("government_state_local", 0.7, "GOV_VALIDATED_BY_GOV_DOMAIN", True)

    return None


def _address_alignment(holder_address: dict[str, Any], record: dict[str, Any]) -> tuple[float, list[str], str]:
    score = 0.0
    reasons: list[str] = []

    if not holder_address:
        return score, reasons, "LOW"

    holder_city = _normalize(holder_address.get("city") or "")
    holder_state = _normalize(holder_address.get("state") or "")
    holder_zip = _normalize(holder_address.get("zip") or "")
    street_parts = [
        holder_address.get("street") or "",
        holder_address.get("street2") or "",
        holder_address.get("street3") or "",
    ]
    holder_street = _normalize(" ".join(part for part in street_parts if part))

    agent = record.get("registered_agent") or {}
    agent_city = _normalize(agent.get("city") or "")
    agent_state = _normalize(agent.get("state") or "")
    agent_zip = _normalize(agent.get("zip") or "")
    agent_street = _normalize(agent.get("line1") or "")

    if holder_zip and agent_zip and holder_zip == agent_zip:
        score += 0.6
        reasons.append("zip_match")
    if holder_city and agent_city and holder_city == agent_city:
        score += 0.2
        reasons.append("city_match")
    if holder_state and agent_state and holder_state == agent_state:
        score += 0.1
        reasons.append("state_match")
    if holder_street and agent_street and holder_street in agent_street:
        score += 0.1
        reasons.append("street_match")

    return min(score, 1.0), reasons, _location_quality(holder_address)


def _extract_suffix(name: str) -> str | None:
    tokens = _normalize(name).split()
    for token in reversed(tokens):
        if token in SUFFIX_KEYWORDS:
            return token
    return None


def _entity_type_score(owner_name: str, record: dict[str, Any]) -> float:
    owner_suffix = _extract_suffix(owner_name)
    if not owner_suffix:
        return 0.5
    candidate_suffix = _extract_suffix(record.get("business_name") or "")
    return 1.0 if candidate_suffix == owner_suffix else 0.0


def _recency_score(last_activity_date: str | None, record: dict[str, Any]) -> float:
    if not last_activity_date:
        return 0.5
    match = re.search(r"\d{4}", str(last_activity_date))
    if not match:
        return 0.5
    last_year = int(match.group(0))
    status_date = record.get("entity_status_date")
    if not status_date:
        return 0.5
    status_match = re.search(r"\d{4}", str(status_date))
    if not status_match:
        return 0.5
    status_year = int(status_match.group(0))
    return 1.0 if status_year >= (last_year - 1) else 0.0


def score_candidates(
    owner_name: str,
    holder_address: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    last_activity_date: str | None = None,
) -> list[CandidateScore]:
    scored: list[CandidateScore] = []
    for record in candidates:
        reasons: list[str] = []
        name_score = _token_overlap(record.get("business_name") or "", owner_name)
        if name_score:
            reasons.append("name_overlap")
        addr_score, addr_reasons, location_quality = _address_alignment(holder_address or {}, record)
        reasons.extend(addr_reasons)

        owner_suffix = _extract_suffix(owner_name)
        candidate_suffix = _extract_suffix(record.get("business_name") or "")
        suffix_score = 1.0 if owner_suffix and candidate_suffix == owner_suffix else 0.0
        if suffix_score:
            reasons.append("suffix_match")

        status = (record.get("entity_status") or "").lower()
        status_score = 1.0 if "active" in status or "good standing" in status else 0.0
        if status_score:
            reasons.append("active_status")

        type_score = _entity_type_score(owner_name, record)
        if type_score == 1.0 and owner_suffix:
            reasons.append("entity_type_match")

        recency_score = _recency_score(last_activity_date, record)

        total = (
            (name_score * 0.30)
            + (suffix_score * 0.15)
            + (addr_score * 0.30)
            + (type_score * 0.10)
            + (recency_score * 0.10)
            + (status_score * 0.05)
        )
        components = {
            "name": round(name_score, 3),
            "suffix": round(suffix_score, 3),
            "address": round(addr_score, 3),
            "entity_type": round(type_score, 3),
            "recency": round(recency_score, 3),
            "status": round(status_score, 3),
        }
        scored.append(
            CandidateScore(
                record=record,
                score=round(total, 3),
                reasons=reasons,
                components=components,
                location_quality=location_quality,
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def choose_candidate(scored: list[CandidateScore]) -> tuple[dict[str, Any] | None, str]:
    if not scored:
        return None, "no_candidates"
    top = scored[0]
    decisive_address = top.location_quality == "HIGH" and top.components.get("address", 0) >= 0.9
    if len(scored) == 1:
        if top.score >= 0.85 or decisive_address:
            return top.record, "selected_single"
        if top.score >= 0.65:
            return top.record, "selected_tentative"
        return None, "needs_review"

    second = scored[1]
    if (top.score >= 0.85 and (top.score - second.score) >= 0.10) or decisive_address:
        return top.record, "selected_confident"
    return None, "needs_review"
