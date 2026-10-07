"""One real embedding call. Runs only with `make test-integration` and an OPENAI_API_KEY.

Guards the contract the catalog tables rely on: the configured model returns 1536 dimensions.
"""

import math

import pytest
from pydantic import ValidationError

from text2sql.config.settings import Settings
from text2sql.llm import LLMConfig
from text2sql.llm.embeddings import embed_texts
from text2sql.retrieval.store import EMBEDDING_DIMENSIONS


def _live_config() -> LLMConfig | None:
    try:
        settings = Settings()  # environment, then backend/.env
    except ValidationError:
        return None
    return LLMConfig.from_settings(settings) if settings.openai_api_key.get_secret_value() else None


LIVE_CONFIG = _live_config()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(LIVE_CONFIG is None, reason="OPENAI_API_KEY is not set"),
]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def test_embedding_model_matches_catalog_dimensions() -> None:
    result = await embed_texts(
        [
            "How many orders were delivered late per state?",
            "Number of late deliveries by customer state",
            "Average review score of furniture products",
        ],
        config=LIVE_CONFIG,
    )
    assert [len(v) for v in result.vectors] == [EMBEDDING_DIMENSIONS] * 3
    late, late_paraphrase, reviews = result.vectors
    assert _cosine(late, late_paraphrase) > _cosine(late, reviews)
    assert result.usage.prompt_tokens > 0
    assert result.usage.cost_usd is not None
    assert result.usage.cost_usd > 0
