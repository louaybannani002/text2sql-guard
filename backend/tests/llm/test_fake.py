import dataclasses
import math
from collections.abc import Callable

import pytest

from tests.support.fake_llm import FakeCompletion, llm_config
from text2sql.config.settings import Settings
from text2sql.guard.input_guard import InputClassification
from text2sql.llm import generate_structured
from text2sql.llm.config import FAKE_PREFIX, LLMConfig
from text2sql.llm.embeddings import embed_texts
from text2sql.llm.fake import UNKNOWN_SQL, fake_vector, question_of, recordings, tables_of
from text2sql.pipeline.generate import SqlDraft, build_messages

FAKE = dataclasses.replace(llm_config(), fake_delay_scale=0.0)


def _messages(question: str) -> list[dict[str, str]]:
    return build_messages(question, "CREATE TABLE shop.orders ();", [])  # type: ignore[return-value]


async def test_generator_gets_the_recorded_sql_and_no_provider_is_called(
    fake_llm: Callable[..., FakeCompletion],
) -> None:
    completion = fake_llm()
    question, sql = next(iter(recordings().items()))
    result = await generate_structured(_messages(question), SqlDraft, "main", config=FAKE)  # type: ignore[arg-type]
    assert result.output.sql == sql
    assert result.output.answerable
    assert result.usage.provider == "fake"
    assert result.usage.cost_usd == 0.0
    assert completion.calls == []


async def test_unknown_questions_get_a_simple_valid_query() -> None:
    result = await generate_structured(
        _messages("Something nobody recorded?"),  # type: ignore[arg-type]
        SqlDraft,
        "main",
        config=FAKE,
    )
    assert result.output.sql == UNKNOWN_SQL
    assert result.output.tables_used == ["shop.orders"]


async def test_classifier_allows_everything_rules_did_not_block() -> None:
    messages = [{"role": "user", "content": "<question>\nhi\n</question>"}]
    result = await generate_structured(messages, InputClassification, "fast", config=FAKE)  # type: ignore[arg-type]
    assert result.output.category == "data_question"


async def test_embeddings_are_deterministic_unit_vectors() -> None:
    result = await embed_texts(["a", "b", "a"], config=FAKE)
    a, b, again = result.vectors
    assert a == again != b
    assert len(a) == 1536
    assert math.isclose(sum(v * v for v in a), 1.0)
    assert fake_vector("a", 8) == fake_vector("a", 8)


async def test_delay_is_scaled() -> None:
    slow = dataclasses.replace(FAKE, fake_delay_scale=0.01)
    result = await generate_structured(_messages("x"), SqlDraft, "main", config=slow)  # type: ignore[arg-type]
    assert 0 < result.usage.latency_ms < 100


def test_settings_turn_fake_mode_on_with_prefixed_models(settings: Settings) -> None:
    fake = LLMConfig.from_settings(settings.model_copy(update={"llm_fake_mode": True}))
    assert fake.fake
    assert all(m.startswith(FAKE_PREFIX) for m in fake.models.values())
    assert fake.embedding_model.startswith(FAKE_PREFIX)
    assert fake.fallbacks == {}
    assert fake.missing_keys() == []  # no provider key needed
    assert not LLMConfig.from_settings(settings).fake  # off by default


def test_fake_mode_is_refused_in_production(fake_env: dict[str, str]) -> None:
    del fake_env
    with pytest.raises(ValueError, match="LLM_FAKE_MODE"):
        Settings(_env_file=None, app_env="production", llm_fake_mode=True)


def test_question_and_tables_helpers() -> None:
    messages = [{"role": "user", "content": "x <question>\n  Orders? \n</question>"}]
    assert question_of(messages) == "Orders?"  # type: ignore[arg-type]
    sql = "WITH t AS (SELECT o.order_id FROM shop.orders AS o) SELECT count(*) FROM t"
    assert tables_of(sql) == ["shop.orders"]
