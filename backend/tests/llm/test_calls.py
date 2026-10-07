import asyncio
from collections.abc import Callable

import pytest
from litellm import exceptions as llm_exc

from tests.support.fake_llm import llm_config
from text2sql.llm import LLMProviderError, LLMTimeoutError, RetryPolicy
from text2sql.llm.calls import call_with_retries


class Script:
    """A zero-argument call that replays outcomes and counts how often it was invoked."""

    def __init__(self, *outcomes: str | BaseException | Callable[[], object]) -> None:
        self.outcomes = list(outcomes)
        self.invocations = 0

    async def __call__(self) -> str:
        self.invocations += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            await asyncio.sleep(10)  # simulates a hung provider
        return str(outcome)


def _rate_limit() -> llm_exc.RateLimitError:
    return llm_exc.RateLimitError("slow down", "openai", "m")


async def test_returns_result_and_attempt_count() -> None:
    call = Script(_rate_limit(), "ok")
    result, attempts = await call_with_retries(call, role="main", model="m", config=llm_config())
    assert (result, attempts) == ("ok", 2)
    assert call.invocations == 2


async def test_each_attempt_invokes_the_factory_again() -> None:
    # A coroutine can only be awaited once: retries must build a new one every time.
    call = Script(_rate_limit(), _rate_limit(), "ok")
    await call_with_retries(call, role="fast", model="m", config=llm_config())
    assert call.invocations == 3


async def test_exhausted_retries_raise_provider_error() -> None:
    call = Script(_rate_limit(), _rate_limit(), _rate_limit())
    with pytest.raises(LLMProviderError) as caught:
        await call_with_retries(call, role="main", model="m", config=llm_config())
    assert (caught.value.attempts, caught.value.status_code) == (3, 429)
    assert caught.value.role == "main"


async def test_max_retries_zero_means_single_attempt() -> None:
    call = Script(_rate_limit())
    config = llm_config(retry=RetryPolicy(max_retries=0, base_delay_s=0.0))
    with pytest.raises(LLMProviderError):
        await call_with_retries(call, role="main", model="m", config=config)
    assert call.invocations == 1


async def test_non_retryable_error_fails_immediately() -> None:
    call = Script(llm_exc.AuthenticationError("bad key", "openai", "m"), "never reached")
    with pytest.raises(LLMProviderError) as caught:
        await call_with_retries(call, role="embedding", model="m", config=llm_config())
    assert call.invocations == 1
    assert caught.value.status_code == 401
    assert caught.value.role == "embedding"


async def test_hard_timeout_is_not_retried() -> None:
    call = Script(lambda: None, "never reached")
    with pytest.raises(LLMTimeoutError):
        await call_with_retries(call, role="main", model="m", config=llm_config(timeout_s=0.05))
    assert call.invocations == 1


async def test_unrelated_exception_is_wrapped_not_retried() -> None:
    call = Script(KeyError("bug in our code"), "never reached")
    with pytest.raises(LLMProviderError) as caught:
        await call_with_retries(call, role="main", model="m", config=llm_config())
    assert call.invocations == 1
    assert isinstance(caught.value.__cause__, KeyError)
