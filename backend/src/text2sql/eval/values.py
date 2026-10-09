"""Value normalisation and tolerant equality for result comparison."""

import math
import re

from text2sql.executor.serialize import JsonValue

type Value = float | str | bool | None
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00(:00(\.0+)?)?([+-]00(:?00)?|Z)?$")
_REL_TOL = 1e-6
_WHOLE_REL_TOL = 0.01  # whole number vs decimal: within 1%
SCALES = (1.0, 100.0, 0.01)  # same unit, percent vs fraction


def normalize(value: JsonValue) -> Value:
    """Comparable form: numbers as float, midnight timestamps as dates, trimmed strings."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if _NUMBER.match(text):
            return float(text)
        midnight = _MIDNIGHT.match(text)
        return midnight.group(1) if midnight else text
    return repr(value)  # lists / objects: compare their text form


def decimals(value: float) -> int:
    """Decimal places as written: 2276.0 -> 0, 4.08 -> 2, 0.75 -> 2."""
    if not math.isfinite(value) or value == int(value):
        return 0
    text = repr(value)
    return len(text.split(".")[1]) if "." in text and "e" not in text else 6


def values_equal(a: Value, b: Value) -> bool:
    """Equality; numbers match at the precision of the less precise side.

    A value rounded to d decimals is within half a unit of the exact one, whatever the
    rounding mode (Postgres rounds half away from zero, Python half to even).
    """
    if isinstance(a, float) and isinstance(b, float):
        if math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=1e-9):
            return True
        digits = min(decimals(a), decimals(b))
        close = abs(a - b) <= 0.5 * 10.0**-digits + 1e-9
        if digits == 0 and close:
            # A whole number may be "rounded to units" or a rounded decimal that lost its
            # trailing zero in serialisation (4.0 -> 4): also require a small relative gap.
            return abs(a - b) <= _WHOLE_REL_TOL * max(abs(a), abs(b))
        return close
    return a == b


def scaled(value: Value, scale: float) -> Value:
    """``value`` times ``scale`` when it is a number."""
    return value * scale if isinstance(value, float) and scale != 1.0 else value


def bucket(value: Value) -> object:
    """Coarse key for grouping candidates (values_equal makes the final call)."""
    return round(value) if isinstance(value, float) else value
