"""Datetime helpers (UTC-first)."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp."""
    return datetime.now(timezone.utc)
