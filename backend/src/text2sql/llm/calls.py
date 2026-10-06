"""Shared timeout + retry wrapper for every provider call (completions and embeddings)."""

import asyncio
from collections.abc import Awaitable, Callable

from text2sql.llm._litellm import Timeout
from text2sql.llm.config import LLMConfig
from text2sql.llm.errors import LLMProviderError, LLMTimeoutError
from text2sql.llm.retry import backoff_delay, is_retryable, status_code
from text2sql.llm.types import UsageRole
from text2sql.observability.logging import get_logger

log = get_logger(__name__)


async def call_with_retries[R](
    call: Callable[[], Awaitable[R]],
    *,
    role: UsageRole,
    model: str,
    config: LLMConfig,
) -> tuple[R, int]:
    """Run ``call`` with a hard timeout, retrying 429/5xx with exponential backoff.

    ``call`` must build a fresh awaitable on every invocation and must not retry by itself
    (pass ``num_retries=0`` and ``max_retries=0`` to LiteLLM).

    Returns:
        The result and the number of attempts it took.

    Raises:
        LLMTimeoutError: The call exceeded ``config.timeout_s``. Not retried.
        LLMProviderError: Non-retryable error, or every attempt failed.
    """
    max_attempts = config.retry.max_retries + 1
    for attempt in range(1, max_attempts + 1):
        try:
            async with asyncio.timeout(config.timeout_s):
                result = await call()
        except (TimeoutError, Timeout) as exc:
            log.warning("llm_timeout", role=role, model=model, attempt=attempt)
            msg = f"{model} did not answer within {config.timeout_s}s"
            raise LLMTimeoutError(msg, role=role, model=model) from exc
        except Exception as exc:
            code = status_code(exc)
            if not is_retryable(exc) or attempt == max_attempts:
                log.warning(
                    "llm_call_failed",
                    role=role,
                    model=model,
                    attempts=attempt,
                    error=type(exc).__name__,
                    status_code=code,
                )
                msg = f"{model} failed after {attempt} attempt(s): {type(exc).__name__}"
                raise LLMProviderError(
                    msg, role=role, model=model, attempts=attempt, status_code=code
                ) from exc
            delay = backoff_delay(attempt, config.retry)
            log.warning(
                "llm_retry",
                role=role,
                model=model,
                attempt=attempt,
                delay_s=round(delay, 3),
                error=type(exc).__name__,
                status_code=code,
            )
            await asyncio.sleep(delay)
        else:
            return result, attempt
    unreachable = "retry loop exited without returning or raising"
    raise AssertionError(unreachable)  # pragma: no cover
