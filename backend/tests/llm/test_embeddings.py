from typing import Any

import pytest
from litellm import exceptions as llm_exc
from litellm.types.utils import EmbeddingResponse, Usage

from tests.support.fake_llm import llm_config
from text2sql.llm import LLMProviderError
from text2sql.llm._litellm import litellm
from text2sql.llm.embeddings import embed_texts


def _response(vectors: list[list[float]], *, shuffled: bool = False) -> EmbeddingResponse:
    data = [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)]
    return EmbeddingResponse(
        model="text-embedding-3-small",
        data=list(reversed(data)) if shuffled else data,
        usage=Usage(prompt_tokens=12, total_tokens=12),
    )


class FakeEmbedding:
    def __init__(self, *outcomes: EmbeddingResponse | BaseException) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> EmbeddingResponse:  # noqa: ANN401
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _install(
    monkeypatch: pytest.MonkeyPatch, *outcomes: EmbeddingResponse | BaseException
) -> FakeEmbedding:
    fake = FakeEmbedding(*outcomes)
    monkeypatch.setattr(litellm, "aembedding", fake)
    return fake


async def test_returns_vectors_in_input_order_with_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _response([[1.0, 0.0], [0.0, 1.0]], shuffled=True))
    result = await embed_texts(["first", "second"], config=llm_config())

    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.usage.role == "embedding"
    assert result.usage.model == "openai/text-embedding-3-small"
    assert result.usage.prompt_tokens == 12
    assert result.usage.cost_usd is not None
    assert result.usage.cost_usd > 0
    call = fake.calls[0]
    assert call["input"] == ["first", "second"]
    assert call["api_key"] == "sk-test-not-a-real-key"
    assert (call["num_retries"], call["max_retries"]) == (0, 0)


async def test_empty_input_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch)
    result = await embed_texts([], config=llm_config())
    assert result.vectors == []
    assert fake.calls == []


async def test_count_mismatch_is_a_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _response([[1.0]]))
    with pytest.raises(LLMProviderError, match="1 embeddings for 2 inputs"):
        await embed_texts(["a", "b"], config=llm_config())


async def test_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(
        monkeypatch,
        llm_exc.RateLimitError("slow down", "openai", "text-embedding-3-small"),
        _response([[1.0]]),
    )
    result = await embed_texts(["a"], config=llm_config())
    assert len(fake.calls) == 2
    assert result.usage.attempts == 2
