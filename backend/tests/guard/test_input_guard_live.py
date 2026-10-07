"""All 40 labelled inputs through the real guard. Needs `make test-integration` + a key."""

import asyncio

import pytest
from pydantic import ValidationError

from tests.guard.cases import ATTACKS, BENIGN
from text2sql.config.settings import Settings
from text2sql.guard.input_guard import InputVerdict, check_input
from text2sql.llm import LLMConfig


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


async def _check_all(questions: list[str]) -> list[InputVerdict]:
    limit = asyncio.Semaphore(8)  # stay well below provider rate limits

    async def one(question: str) -> InputVerdict:
        async with limit:
            return await check_input(question, config=LIVE_CONFIG)

    return await asyncio.gather(*(one(q) for q in questions))


async def test_benign_questions_pass() -> None:
    verdicts = await _check_all(BENIGN)
    wrongly_blocked = [
        (q, v.category) for q, v in zip(BENIGN, verdicts, strict=True) if not v.allowed
    ]
    assert wrongly_blocked == []


async def test_attacks_are_blocked() -> None:
    verdicts = await _check_all(ATTACKS)
    let_through = [q for q, v in zip(ATTACKS, verdicts, strict=True) if v.allowed]
    assert let_through == []
    assert {v.category for v in verdicts} <= {
        "sql_command",
        "prompt_injection",
        "invalid_input",
        "harmful",
        "off_topic",
    }
