"""Timezone and work-hours helpers. Expanded as the scheduling engine develops."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
