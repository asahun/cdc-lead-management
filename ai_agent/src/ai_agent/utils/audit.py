from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_audit(state: dict[str, Any]) -> dict[str, Any]:
    audit = state.get("audit")
    if not isinstance(audit, dict):
        audit = {"steps": [], "errors": []}
    audit.setdefault("steps", [])
    audit.setdefault("errors", [])
    return audit


def start_step(audit: dict[str, Any], name: str) -> dict[str, Any]:
    step = {
        "name": name,
        "started_at": _now(),
        "ended_at": None,
        "notes": "",
    }
    audit["steps"].append(step)
    return step


def end_step(step: dict[str, Any], notes: str = "") -> None:
    step["ended_at"] = _now()
    duration_note = ""
    try:
        started = datetime.fromisoformat(step["started_at"])
        ended = datetime.fromisoformat(step["ended_at"])
        duration = (ended - started).total_seconds()
        duration_note = f"duration={duration:.2f}s"
    except Exception:
        duration_note = ""
    combined = notes.strip()
    if duration_note:
        combined = f"{combined} | {duration_note}" if combined else duration_note
    step["notes"] = combined


def add_error(audit: dict[str, Any], message: str) -> None:
    audit.setdefault("errors", []).append(message)
