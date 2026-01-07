import logging
import re
from datetime import datetime
import time
from typing import Any

import psycopg2

from ai_agent.settings import Settings

logger = logging.getLogger(__name__)


_SUFFIX_RE = re.compile(
    r"\b(inc|incorporated|corp|corporation|llc|l\.l\.c\.|ltd|limited|co|company|lp|l\.p\.|llp|l\.l\.p\.)\b",
    flags=re.IGNORECASE,
)
_SUFFIX_TOKENS = [
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "llc",
    "l.l.c.",
    "ltd",
    "limited",
    "co",
    "company",
    "lp",
    "l.p.",
    "llp",
    "l.l.p.",
]


def _normalize_name(name: str, remove_suffix: bool = False) -> str:
    normalized = (name or "").lower().strip()
    normalized = re.sub(r"[.,;:!?]", "", normalized)
    if remove_suffix:
        normalized = _SUFFIX_RE.sub("", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def _reorder_first_token(normalized: str) -> str:
    parts = normalized.split()
    if len(parts) < 2:
        return normalized
    return " ".join(parts[1:] + parts[:1])


def _extract_suffix(name: str) -> str | None:
    lowered = (name or "").lower()
    for token in _SUFFIX_TOKENS:
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            return token.replace(".", "")
    return None


def _score_match(candidate: str, target: str, status: str | None, suffix_match: bool) -> float:
    score = 0.0
    if candidate == target:
        score = 4.0
    elif candidate.startswith(target) or target.startswith(candidate):
        score = 2.5
    elif target in candidate:
        score = 1.5

    candidate_tokens = set(candidate.split())
    target_tokens = set(target.split())
    if candidate_tokens and target_tokens:
        overlap = len(candidate_tokens & target_tokens) / len(target_tokens)
        score += overlap

    status_lower = (status or "").lower()
    if "active" in status_lower or "good standing" in status_lower:
        score += 0.25
    if suffix_match:
        score += 0.5
    return score


def _parse_status_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def lookup_business(business_name: str, state: str, settings: Settings) -> dict[str, Any]:
    """Query local GA SOS tables for matching entities."""
    _ = state
    base = _normalize_name(business_name, remove_suffix=False)
    if not base:
        return {
            "records": [],
            "search_names_tried": [],
            "matched_name": None,
        }

    logger.info("GA SOS lookup begin: business_name=%s", business_name)
    candidates = [base]
    base_no_suffix = _normalize_name(business_name, remove_suffix=True)
    if base_no_suffix and base_no_suffix != base:
        candidates.append(base_no_suffix)

    reordered = _reorder_first_token(base_no_suffix or base)
    if reordered and reordered not in candidates:
        candidates.append(reordered)

    query = """
        SELECT b.control_number,
               b.business_name,
               b.entity_status,
               b.entity_status_date,
               ra.name,
               ra.line1,
               ra.line2,
               ra.city,
               ra.state,
               ra.zip
          FROM biz_entity b
          LEFT JOIN biz_entity_registered_agents ra
            ON ra.registered_agent_id = b.registered_agent_id
         WHERE LOWER(b.business_name) LIKE %s
         ORDER BY LOWER(b.business_name)
         LIMIT 25
    """

    results_map: dict[str, dict[str, Any]] = {}
    conn = None
    try:
        conn = psycopg2.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            connect_timeout=5,
        )
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("SET statement_timeout TO %s", (settings.ga_sos_timeout_ms,))
                for candidate in candidates:
                    start = time.monotonic()
                    try:
                        cursor.execute(query, (f"{candidate}%",))
                        for row in cursor.fetchall():
                            control_number = row[0] or row[1]
                            if control_number in results_map:
                                continue
                            results_map[control_number] = {
                                "control_number": row[0],
                                "business_name": row[1],
                                "entity_status": row[2],
                                "entity_status_date": row[3],
                                "registered_agent": {
                                    "name": row[4],
                                    "line1": row[5],
                                    "line2": row[6],
                                    "city": row[7],
                                    "state": row[8],
                                    "zip": row[9],
                                }
                                if row[4]
                                else None,
                            }
                    except Exception as exc:
                        logger.warning("GA SOS query failed for candidate=%s: %s", candidate, exc)
                    duration = time.monotonic() - start
                    logger.info("GA SOS query candidate=%s duration=%.2fs", candidate, duration)
    except Exception as exc:
        logger.warning("GA SOS lookup failed: %s", exc)
        return {
            "records": [],
            "search_names_tried": candidates,
            "matched_name": None,
        }
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    results = list(results_map.values())

    if not results:
        logger.info("GA SOS lookup: no results found for business_name=%s", business_name)
        return {
            "records": [],
            "search_names_tried": candidates,
            "matched_name": None,
        }

    target = base_no_suffix or base
    owner_suffix = _extract_suffix(business_name)
    scored = []
    for item in results:
        candidate_name = _normalize_name(item.get("business_name"), remove_suffix=True)
        candidate_suffix = _extract_suffix(item.get("business_name"))
        score = _score_match(
            candidate_name,
            target,
            item.get("entity_status"),
            suffix_match=bool(owner_suffix and candidate_suffix == owner_suffix),
        )
        status_date = _parse_status_date(item.get("entity_status_date"))
        scored.append((score, status_date, item))
        logger.debug("GA SOS match: candidate=%s, score=%.2f", item.get("business_name"), score)

    scored.sort(key=lambda x: (x[0], x[1] or datetime.min), reverse=True)
    best_score = scored[0][0] if scored else 0.0
    best = [item for score, _, item in scored if score == best_score]

    logger.info("GA SOS lookup: best_score=%.2f, returning %d matches", best_score, len(best[:1]))
    if best:
        matched_name = best[0].get("business_name")
        return {
            "records": best[:5],
            "search_names_tried": candidates,
            "matched_name": matched_name,
        }
    return {
        "records": [],
        "search_names_tried": candidates,
        "matched_name": None,
    }
