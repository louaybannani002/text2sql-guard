"""One real call to OpenAI. Runs only with `make test-integration` and an OPENAI_API_KEY."""

import os

import pytest
from pydantic import BaseModel, Field, ValidationError

from text2sql.config.settings import Settings
from text2sql.llm import LLMConfig, generate_structured


def _live_config() -> LLMConfig | None:
    try:
        settings = Settings()  # environment, then backend/.env
    except ValidationError:
        return None
    key = settings.openai_api_key.get_secret_value() or os.environ.get("OPENAI_API_KEY", "")
    return LLMConfig.from_settings(settings) if key else None


LIVE_CONFIG = _live_config()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(LIVE_CONFIG is None, reason="OPENAI_API_KEY is not set"),
]


class Capital(BaseModel):
    country: str = Field(description="Country name in English")
    capital: str = Field(description="Capital city in English")


async def test_fast_model_returns_structured_output_with_usage() -> None:
    assert LIVE_CONFIG is not None
    result = await generate_structured(
        [
            {"role": "system", "content": "Answer with the requested JSON only."},
            {"role": "user", "content": "What is the capital of Brazil?"},
        ],
        Capital,
        "fast",
        config=LIVE_CONFIG,
    )

    assert result.output.capital.lower().replace("í", "i") == "brasilia"
    usage = result.usage
    assert usage.model == LIVE_CONFIG.models["fast"]
    assert usage.prompt_tokens > 0
    assert usage.completion_tokens > 0
    assert usage.cost_usd is not None
    assert usage.cost_usd > 0
    assert usage.attempts >= 1
