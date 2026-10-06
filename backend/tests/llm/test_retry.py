import random

import pytest
from litellm import exceptions as llm_exc

from text2sql.llm.config import RetryPolicy
from text2sql.llm.retry import backoff_delay, is_retryable, status_code


class _MaxRng(random.Random):
    """Always returns the upper bound, exposing the backoff cap."""

    def uniform(self, a: float, b: float) -> float:
        del a
        return b


def test_backoff_is_exponential_and_capped() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=5.0)
    caps = [backoff_delay(retry, policy, _MaxRng()) for retry in range(1, 6)]
    assert caps == [1.0, 2.0, 4.0, 5.0, 5.0]


def test_backoff_has_jitter_within_bounds() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=8.0)
    rng = random.Random(42)  # noqa: S311 - deterministic test jitter
    delays = [backoff_delay(2, policy, rng) for _ in range(50)]
    assert all(0 <= d <= 2.0 for d in delays)
    assert len(set(delays)) > 1


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (llm_exc.RateLimitError("m", "openai", "gpt"), True),
        (llm_exc.InternalServerError("m", "openai", "gpt"), True),
        (llm_exc.ServiceUnavailableError("m", "openai", "gpt"), True),
        (llm_exc.APIError(599, "m", "openai", "gpt"), True),
        (llm_exc.Timeout("m", "gpt", "openai"), False),
        (llm_exc.BadRequestError("m", "gpt", "openai"), False),
        (llm_exc.AuthenticationError("m", "openai", "gpt"), False),
        (ValueError("not a provider error"), False),
    ],
)
def test_is_retryable(error: BaseException, retryable: bool) -> None:  # noqa: FBT001
    assert is_retryable(error) is retryable


def test_status_code_ignores_non_int() -> None:
    error = ValueError("x")
    error.status_code = "500"  # type: ignore[attr-defined]
    assert status_code(error) is None
