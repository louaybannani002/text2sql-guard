"""Which provider errors are worth retrying, and how long to wait."""

import random

from text2sql.llm._litellm import RateLimitError, Timeout
from text2sql.llm.config import RetryPolicy

_HTTP_SERVER_ERROR = 500


def status_code(exc: BaseException) -> int | None:
    """HTTP status attached to a LiteLLM / OpenAI exception, if any."""
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def is_retryable(exc: BaseException) -> bool:
    """Rate limits (429) and server-side failures (5xx). Timeouts are not retried."""
    if isinstance(exc, Timeout):
        return False
    if isinstance(exc, RateLimitError):
        return True
    code = status_code(exc)
    return code is not None and code >= _HTTP_SERVER_ERROR


def backoff_delay(retry: int, policy: RetryPolicy, rng: random.Random | None = None) -> float:
    """Seconds to wait before retry number ``retry`` (1-based)."""
    cap = min(policy.max_delay_s, policy.base_delay_s * 2 ** (retry - 1))
    return (rng or random).uniform(0, cap)  # jitter, not cryptography
