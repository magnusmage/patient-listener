"""Timezone lookup with a zero-dependency UTC fallback on Windows."""
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def schedule_timezone(name: str):
    if name == 'UTC':
        return timezone.utc
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError('Unknown or unavailable IANA timezone; check the name and install tzdata if needed') from exc
