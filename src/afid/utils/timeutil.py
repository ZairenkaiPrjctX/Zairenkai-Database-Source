from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> str:
    """Current time as ISO 8601 UTC with second precision, e.g. 2026-10-18T19:20:00Z."""
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
