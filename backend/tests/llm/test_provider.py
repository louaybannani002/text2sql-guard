import asyncio
from collections.abc import Callable

import pytest
from litellm import ModelResponse
from litellm import exceptions as llm_exc
from pydantic import BaseModel

from tests.support.fake_llm import FakeCompletion
from tests.support.fake_llm import llm_config as _config
from tests.support.fake_llm import model_response as _response
from text2sql.llm import (
    LLMOutputValidationError,
    LLMProviderError,
    LLMTimeoutError,
    Message,
    generate_structured,
)

MESSAGES: list[Message] = [{"role": "user", "content": "Which country has the most orders?"}]


class Answer(BaseModel):
    country: str
    orders: int


# ---------------------------------------------------------------- happy path


async def test_returns_validated_object_and_usage(fake_llm: Callable[..., FakeCompletion]) -> None:
    fake_llm(_response('{"country": "BR", "orders": 99441}'))
    result = await generate_structured(MESSAGES, Answer, "fast", config=_config())

    assert result.output == Answer(country="BR", orders=99441)
    usage = result.usage
    assert (usage.role, usage.model) == ("fast", "openai/gpt-5.4-mini")
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (120, 30, 150)
    assert usage.attempts == 1
    assert usage.latency_ms >= 0
    assert usage.cost_usd is not None
    assert usage.cost_usd > 0


@pytest.mark.parametrize(
    ("role", "model"),
    [("main", "openai/gpt-5.4"), ("fast", "openai/gpt-5.4-mini")],
)
async def test_role_selects_configured_model_and_key(
    fake_llm: Callable[..., FakeCompletion], role: str, model: str
) -> None:
    completion = fake_llm(_response('{"country": "BR", "orders": 1}'))
    await generate_structured(MESSAGES, Answer, role, config=_config())  # type: ignore[arg-type]

    call = completion.calls[0]
    assert call["model"] == model
    assert call["api_key"] == "sk-test-not-a-real-key"
    assert call["api_base"] is None
    assert call["response_format"] is Answer
    assert call["messages"] == MESSAGES
    assert call["timeout"] == 5.0
    # LiteLLM and the OpenAI SDK must not retry on their own.
    assert (call["num_retries"], call["max_retries"]) == (0, 0)


async def test_local_role_uses_api_base_and_no_openai_key(
    fake_llm: Callable[..., FakeCompletion],
) -> None:
    completion = fake_llm(_response('{"country": "BR", "orders": 1}', model="qwen2.5-coder:7b"))
    result = await generate_structured(MESSAGES, Answer, "local", config=_config())

    call = completion.calls[0]
    assert call["model"] == "ollama_chat/qwen2.5-coder:7b"
    assert call["api_base"] == "http://127.0.0.1:11434"
    assert call["api_key"] is None
    assert result.usage.cost_usd is None  # unpriced model: unknown, not zero


async def test_strips_markdown_code_fence(fake_llm: Callable[..., FakeCompletion]) -> None:
    fake_llm(_response('```json\n{"country": "BR", "orders": 7}\n```'))
    result = await generate_structured(MESSAGES, Answer, "fast", config=_config())
    assert result.output.orders == 7


# ---------------------------------------------------------------- retries


RETRYABLE: dict[str, Callable[[], BaseException]] = {
    "rate_limit_429": lambda: llm_exc.RateLimitError("slow down", "openai", "gpt-5.4-mini"),
    "internal_500": lambda: llm_exc.InternalServerError("boom", "openai", "gpt-5.4-mini"),
    "bad_gateway_502": lambda: llm_exc.BadGatewayError("boom", "openai", "gpt-5.4-mini"),
    "unavailable_503": lambda: llm_exc.ServiceUnavailableError("down", "openai", "gpt-5.4-mini"),
    "api_error_504": lambda: llm_exc.APIError(504, "gw timeout", "openai", "gpt-5.4-mini"),
    "connection": lambda: llm_exc.APIConnectionError("reset", "openai", "gpt-5.4-mini"),
}

NOT_RETRYABLE: dict[str, Callable[[], BaseException]] = {
    "bad_request_400": lambda: llm_exc.BadRequestError("bad", "gpt-5.4-mini", "openai"),
    "auth_401": lambda: llm_exc.AuthenticationError("no", "openai", "gpt-5.4-mini"),
    "context_window": lambda: llm_exc.ContextWindowExceededError("long", "gpt-5.4-mini", "openai"),
}


@pytest.mark.parametrize("make_error", RETRYABLE.values(), ids=RETRYABLE.keys())
async def test_retries_rate_limits_and_5xx(
    fake_llm: Callable[..., FakeCompletion], make_error: Callable[[], BaseException]
) -> None:
    completion = fake_llm(make_error(), make_error(), _response('{"country": "BR", "orders": 1}'))
    result = await generate_structured(MESSAGES, Answer, "fast", config=_config())
    assert len(completion.calls) == 3
    assert result.usage.attempts == 3


async def test_gives_up_after_two_retries(fake_llm: Callable[..., FakeCompletion]) -> None:
    errors = [RETRYABLE["rate_limit_429"]() for _ in range(4)]
    completion = fake_llm(*errors)
    with pytest.raises(LLMProviderError) as caught:
        await generate_structured(MESSAGES, Answer, "fast", config=_config())

    assert len(completion.calls) == 3  # 1 call + 2 retries
    assert caught.value.attempts == 3
    assert caught.value.status_code == 429
    assert isinstance(caught.value.__cause__, llm_exc.RateLimitError)


@pytest.mark.parametrize("make_error", NOT_RETRYABLE.values(), ids=NOT_RETRYABLE.keys())
async def test_client_errors_are_not_retried(
    fake_llm: Callable[..., FakeCompletion], make_error: Callable[[], BaseException]
) -> None:
    completion = fake_llm(make_error())
    with pytest.raises(LLMProviderError) as caught:
        await generate_structured(MESSAGES, Answer, "fast", config=_config())
    assert len(completion.calls) == 1
    assert caught.value.attempts == 1


async def test_backoff_sleeps_between_retries(
    fake_llm: Callable[..., FakeCompletion], monkeypatch: pytest.MonkeyPatch
) -> None:
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay: float) -> None:
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr("text2sql.llm.provider.asyncio.sleep", recording_sleep)
    monkeypatch.setattr("text2sql.llm.provider.backoff_delay", lambda retry, _policy: 0.1 * retry)
    fake_llm(
        RETRYABLE["internal_500"](),
        RETRYABLE["internal_500"](),
        _response('{"country": "BR", "orders": 1}'),
    )

    await generate_structured(MESSAGES, Answer, "fast", config=_config())
    assert delays == [0.1, 0.2]


# ---------------------------------------------------------------- timeouts


async def test_hung_provider_times_out_without_retry(
    fake_llm: Callable[..., FakeCompletion],
) -> None:
    async def hang() -> ModelResponse:
        await asyncio.sleep(5)
        return _response("{}")

    completion = fake_llm(hang)
    with pytest.raises(LLMTimeoutError):
        await generate_structured(MESSAGES, Answer, "fast", config=_config(timeout_s=0.05))
    assert len(completion.calls) == 1


async def test_provider_timeout_maps_to_timeout_error(
    fake_llm: Callable[..., FakeCompletion],
) -> None:
    completion = fake_llm(llm_exc.Timeout("too slow", "gpt-5.4-mini", "openai"))
    with pytest.raises(LLMTimeoutError):
        await generate_structured(MESSAGES, Answer, "fast", config=_config())
    assert len(completion.calls) == 1


# ---------------------------------------------------------------- invalid output


@pytest.mark.parametrize(
    "content",
    [
        "not json at all",
        '{"country": "BR"}',  # missing field
        '{"country": "BR", "orders": "many"}',  # wrong type
        "",
    ],
)
async def test_invalid_output_raises_validation_error(
    fake_llm: Callable[..., FakeCompletion], content: str
) -> None:
    fake_llm(_response(content))
    with pytest.raises(LLMOutputValidationError) as caught:
        await generate_structured(MESSAGES, Answer, "fast", config=_config())

    error = caught.value
    assert error.raw_output == content
    assert error.errors
    assert error.usage.total_tokens == 150  # spent even though unusable
    assert "Answer" in str(error)


async def test_raw_output_is_not_in_error_message(fake_llm: Callable[..., FakeCompletion]) -> None:
    fake_llm(_response('{"secret_customer_city": "campinas"}'))
    with pytest.raises(LLMOutputValidationError) as caught:
        await generate_structured(MESSAGES, Answer, "fast", config=_config())
    assert "campinas" not in str(caught.value)


async def test_refusal_is_reported(fake_llm: Callable[..., FakeCompletion]) -> None:
    fake_llm(_response(None, refusal="I can't help with that."))
    with pytest.raises(LLMOutputValidationError) as caught:
        await generate_structured(MESSAGES, Answer, "fast", config=_config())
    assert caught.value.refusal == "I can't help with that."
