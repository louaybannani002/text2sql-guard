"""``generate_structured``: one LLM call returning a validated Pydantic object and its usage."""

import asyncio
import re
import time
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from text2sql.config.settings import get_settings
from text2sql.llm._litellm import Timeout, litellm
from text2sql.llm.config import LLMConfig, ModelTarget
from text2sql.llm.errors import LLMOutputValidationError, LLMProviderError, LLMTimeoutError
from text2sql.llm.retry import backoff_delay, is_retryable, status_code
from text2sql.llm.types import LLMResult, Message, ModelRole, Usage
from text2sql.observability.logging import get_logger

log = get_logger(__name__)

# Some models (notably local ones) wrap JSON in a Markdown code fence despite instructions.
_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(?P<body>.*?)\n?\s*```\s*$", re.DOTALL)


async def generate_structured[T: BaseModel](
    messages: Sequence[Message],
    response_model: type[T],
    model_role: ModelRole,
    *,
    config: LLMConfig | None = None,
) -> LLMResult[T]:
    """Ask the model for ``response_model`` and return it validated, with usage.

    Args:
        messages: Chat history; the last message is normally the user request.
        response_model: Pydantic model the answer must satisfy (sent as a JSON schema).
        model_role: Which configured model to use: ``main``, ``fast`` or ``local``.
        config: Override for tests; defaults to the application settings.

    Raises:
        LLMTimeoutError: No answer within ``config.timeout_s``.
        LLMProviderError: Non-retryable provider error, or retries exhausted.
        LLMOutputValidationError: The answer does not validate against ``response_model``.
    """
    config = config or LLMConfig.from_settings(get_settings())
    target = config.target(model_role)
    started = time.perf_counter()
    response, attempts = await _complete_with_retries(
        messages, response_model, model_role, target, config
    )
    usage = _usage(response, model_role, target.model, started, attempts)
    log.info("llm_call", **usage.model_dump(), schema=response_model.__name__)
    return LLMResult(_validate(response, response_model, usage), usage)


async def _complete_with_retries(
    messages: Sequence[Message],
    response_model: type[BaseModel],
    role: ModelRole,
    target: ModelTarget,
    config: LLMConfig,
) -> tuple[Any, int]:
    max_attempts = config.retry.max_retries + 1
    for attempt in range(1, max_attempts + 1):
        try:
            async with asyncio.timeout(config.timeout_s):
                response = await litellm.acompletion(
                    model=target.model,
                    messages=list(messages),
                    response_format=response_model,
                    timeout=config.timeout_s,
                    api_key=target.api_key.get_secret_value() if target.api_key else None,
                    api_base=target.api_base,
                    num_retries=0,  # retries are ours: exact count, our backoff, our logs
                    max_retries=0,  # ...and the OpenAI SDK must not retry underneath us
                )
        except (TimeoutError, Timeout) as exc:
            log.warning("llm_timeout", role=role, model=target.model, attempt=attempt)
            msg = f"{target.model} did not answer within {config.timeout_s}s"
            raise LLMTimeoutError(msg, role=role, model=target.model) from exc
        except Exception as exc:
            code = status_code(exc)
            if not is_retryable(exc) or attempt == max_attempts:
                log.warning(
                    "llm_call_failed",
                    role=role,
                    model=target.model,
                    attempts=attempt,
                    error=type(exc).__name__,
                    status_code=code,
                )
                msg = f"{target.model} failed after {attempt} attempt(s): {type(exc).__name__}"
                raise LLMProviderError(
                    msg, role=role, model=target.model, attempts=attempt, status_code=code
                ) from exc
            delay = backoff_delay(attempt, config.retry)
            log.warning(
                "llm_retry",
                role=role,
                model=target.model,
                attempt=attempt,
                delay_s=round(delay, 3),
                error=type(exc).__name__,
                status_code=code,
            )
            await asyncio.sleep(delay)
        else:
            return response, attempt
    unreachable = "retry loop exited without returning or raising"
    raise AssertionError(unreachable)  # pragma: no cover


def _usage(response: Any, role: ModelRole, model: str, started: float, attempts: int) -> Usage:  # noqa: ANN401
    tokens = getattr(response, "usage", None)
    prompt = int(getattr(tokens, "prompt_tokens", 0) or 0)
    completion = int(getattr(tokens, "completion_tokens", 0) or 0)
    try:
        cost: float | None = float(litellm.completion_cost(completion_response=response))
    except Exception:  # noqa: BLE001 - unpriced model (e.g. local): cost is unknown, not zero
        cost = None
    return Usage(
        role=role,
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=int(getattr(tokens, "total_tokens", 0) or prompt + completion),
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        cost_usd=cost,
        attempts=attempts,
    )


def _validate[T: BaseModel](response: Any, response_model: type[T], usage: Usage) -> T:  # noqa: ANN401
    message = response.choices[0].message
    content: str = message.content or ""
    refusal: str | None = getattr(message, "refusal", None)
    fenced = _CODE_FENCE.match(content)
    payload = fenced["body"] if fenced else content
    try:
        if not payload.strip():
            msg = "refused" if refusal else "returned no content"
            raise ValueError(msg)  # noqa: TRY301 - funnels into the single error path below
        return response_model.model_validate_json(payload)
    except (ValidationError, ValueError) as exc:
        errors = exc.errors() if isinstance(exc, ValidationError) else [{"msg": str(exc)}]
        log.warning(
            "llm_output_invalid",
            role=usage.role,
            model=usage.model,
            schema=response_model.__name__,
            error_count=len(errors),
            refused=refusal is not None,
        )
        msg = (
            f"{usage.model} output does not match {response_model.__name__}:"
            f" {len(errors)} validation error(s)"
        )
        raise LLMOutputValidationError(
            msg,
            role=usage.role,
            model=usage.model,
            raw_output=content,
            errors=errors,
            usage=usage,
            refusal=refusal,
        ) from exc
