"""Convert database values to JSON-safe Python values (what ``json.dumps`` accepts).

- Decimal -> int when integral, float when exactly representable, else str (no silent rounding)
- datetime/date/time -> ISO 8601 str; timedelta -> seconds (float)
- UUID -> str; bytes -> base64 str; NaN/Infinity -> str
- lists/tuples/records -> lists, recursively; anything else -> str
"""

import base64
import datetime as dt
import math
import uuid
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal

type JsonValue = bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None

_MAX_FLOAT_DIGITS = 15  # a double holds 15 significant decimal digits exactly


def _decimal(value: Decimal) -> JsonValue:
    if not value.is_finite():
        return str(value)
    if value == value.to_integral_value():
        return int(value)
    digits = len(value.normalize().as_tuple().digits)
    return float(value) if digits <= _MAX_FLOAT_DIGITS else str(value)


def to_json_value(value: object) -> JsonValue:  # noqa: PLR0911 - one branch per type
    """JSON-safe representation of one database value."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, dt.date | dt.time):  # datetime is a date
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, Mapping):
        return {str(k): to_json_value(v) for k, v in value.items()}
    if isinstance(value, Sequence):
        return [to_json_value(v) for v in value]
    return str(value)


def to_json_row(row: Iterable[object]) -> list[JsonValue]:
    """JSON-safe representation of one row (iterating an asyncpg Record yields its values)."""
    return [to_json_value(value) for value in row]
