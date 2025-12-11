"""
Date and time utility functions.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import os

APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "America/New_York"))


def previous_monday_cutoff(now: datetime | None = None) -> datetime:
    """
    Return the most recent Monday at 6 PM (APP_TIMEZONE). If we're earlier than
    this week's Monday 6 PM, go back one more week. Result is returned in UTC.
    """
    now_local = (now or datetime.now(APP_TIMEZONE)).astimezone(APP_TIMEZONE)
    days_since_monday = now_local.weekday()
    monday_local = (now_local - timedelta(days=days_since_monday)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )
    if now_local < monday_local:
        monday_local -= timedelta(days=7)
    return monday_local.astimezone(timezone.utc)

