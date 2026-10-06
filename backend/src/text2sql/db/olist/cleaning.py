"""Pure parsers turning raw CSV strings into typed, cleaned values.

Every parser maps empty / whitespace-only strings to ``None``; NOT NULL columns then make the
database reject missing required values loudly instead of silently loading junk.
"""

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

type Parser = Callable[[str], object]

_TIMESTAMP_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def text(raw: str) -> str | None:
    """Trimmed text, or ``None`` if empty."""
    value = raw.strip()
    return value or None


def integer(raw: str) -> int | None:
    """Integer; tolerates a ``.0`` suffix (e.g. ``"3.0"``)."""
    value = raw.strip()
    if not value:
        return None
    return int(float(value)) if "." in value else int(value)


def decimal(raw: str) -> Decimal | None:
    """Exact decimal for money values."""
    value = raw.strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        msg = f"not a decimal: {value!r}"
        raise ValueError(msg) from exc


def floating(raw: str) -> float | None:
    """Floating-point number (coordinates)."""
    value = raw.strip()
    return float(value) if value else None


def timestamp(raw: str) -> datetime | None:
    """Naive timestamp in ``YYYY-MM-DD HH:MM:SS`` (source data is local Brazilian time)."""
    value = raw.strip()
    if not value:
        return None
    # fromisoformat is ~10x faster than strptime but lenient (dates, offsets, 'T'), so the
    # exact shape is checked first.
    if not _TIMESTAMP_SHAPE.fullmatch(value):
        msg = f"time data {value!r} does not match format 'YYYY-MM-DD HH:MM:SS'"
        raise ValueError(msg)
    return datetime.fromisoformat(value)


def date_only(raw: str) -> date | None:
    """Calendar date from ``YYYY-MM-DD`` or a midnight timestamp; rejects any other time."""
    value = raw.strip()
    if not value:
        return None
    day, _, time = value.partition(" ")
    if time not in {"", "00:00:00"}:
        msg = f"expected a date or midnight timestamp, got {value!r}"
        raise ValueError(msg)
    return date.fromisoformat(day)
