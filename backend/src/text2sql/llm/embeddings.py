"""Text embeddings through LiteLLM, with the same timeout/retry/usage rules as completions."""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from text2sql.config.settings import get_settings
from text2sql.llm._litellm import litellm
from text2sql.llm.calls import call_with_retries
from text2sql.llm.config import LLMConfig
from text2sql.llm.errors import LLMProviderError
from text2sql.llm.types import Usage
from text2sql.observability.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """One vector per input text, in input order, plus the usage of the call."""

    vectors: list[list[float]]
    usage: Usage


async def embed_texts(texts: Sequence[str], *, config: LLMConfig | None = None) -> EmbeddingResult:
    """Embed ``texts`` with the configured embedding model in one request.

    Raises:
        LLMTimeoutError: No answer within the timeout.
        LLMProviderError: Provider failure, or a response that does not match the input.
    """
    config = config or LLMConfig.from_settings(get_settings())
    target = config.target("embedding")
    if not texts:
        nothing = Usage(
            role="embedding",
            model=target.model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            cost_usd=0.0,
            attempts=1,
        )
        return EmbeddingResult([], nothing)
    started = time.perf_counter()
    response, attempts = await call_with_retries(
        lambda: litellm.aembedding(
            model=target.model,
            input=list(texts),
            timeout=config.timeout_s,
            api_key=target.api_key.get_secret_value() if target.api_key else None,
            api_base=target.api_base,
            num_retries=0,
            max_retries=0,
        ),
        role="embedding",
        model=target.model,
        config=config,
    )
    data = sorted(response.data, key=lambda item: item["index"])
    if len(data) != len(texts):
        msg = f"{target.model} returned {len(data)} embeddings for {len(texts)} inputs"
        raise LLMProviderError(
            msg, role="embedding", model=target.model, attempts=attempts, status_code=None
        )
    usage = _usage(response, target.model, started, attempts)
    log.info("llm_embedding", **usage.model_dump(), inputs=len(texts))
    return EmbeddingResult([list(map(float, item["embedding"])) for item in data], usage)


def _usage(response: Any, model: str, started: float, attempts: int) -> Usage:  # noqa: ANN401
    tokens = int(getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0)
    try:
        cost: float | None = float(
            litellm.completion_cost(completion_response=response, call_type="aembedding")
        )
    except Exception:  # noqa: BLE001 - unpriced model: cost unknown, not zero
        cost = None
    return Usage(
        role="embedding",
        model=model,
        prompt_tokens=tokens,
        completion_tokens=0,
        total_tokens=tokens,
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        cost_usd=cost,
        attempts=attempts,
    )
