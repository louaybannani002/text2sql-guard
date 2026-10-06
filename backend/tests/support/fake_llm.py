"""A scripted stand-in for ``litellm.acompletion`` and helpers to build its responses."""

from collections.abc import Awaitable, Callable
from typing import Any

from litellm import ModelResponse
from pydantic import SecretStr

from text2sql.llm import LLMConfig, RetryPolicy

type Outcome = ModelResponse | BaseException | Callable[[], Awaitable[ModelResponse]]


def llm_config(**overrides: Any) -> LLMConfig:  # noqa: ANN401
    """An LLMConfig with fake credentials and no backoff delay."""
    defaults: dict[str, Any] = {
        "models": {
            "main": "openai/gpt-5.4",
            "fast": "openai/gpt-5.4-mini",
            "local": "ollama_chat/qwen2.5-coder:7b",
        },
        "embedding_model": "openai/text-embedding-3-small",
        "timeout_s": 5.0,
        "retry": RetryPolicy(max_retries=2, base_delay_s=0.0),
        "openai_api_key": SecretStr("sk-test-not-a-real-key"),
        "local_api_base": "http://127.0.0.1:11434",
    }
    return LLMConfig(**(defaults | overrides))


def model_response(
    content: str | None,
    model: str = "gpt-5.4-mini",
    **message: Any,  # noqa: ANN401
) -> ModelResponse:
    """A LiteLLM response with one assistant message and fixed token usage (120 + 30)."""
    return ModelResponse(
        model=model,
        choices=[{"message": {"role": "assistant", "content": content, **message}}],
        usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    )


class FakeCompletion:
    """Replays scripted outcomes in order and records every call's keyword arguments."""

    def __init__(self, *outcomes: Outcome) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> ModelResponse:  # noqa: ANN401
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome
