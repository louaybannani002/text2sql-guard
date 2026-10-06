"""One real SQL generation. Runs only with `make test-integration` and an OPENAI_API_KEY."""

from pathlib import Path

import pytest
import sqlglot
from pydantic import ValidationError
from sqlglot import exp

from text2sql.config.settings import Settings
from text2sql.llm import LLMConfig
from text2sql.pipeline.generate import generate_sql

# Snapshot of what the schema catalog will render (readable columns only).
SCHEMA_CONTEXT = (Path(__file__).parent / "fixtures" / "shop_schema_context.md").read_text(
    encoding="utf-8"
)


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


async def test_late_deliveries_per_state() -> None:
    result = await generate_sql(
        "How many orders were delivered late per state?", SCHEMA_CONTEXT, [], config=LIVE_CONFIG
    )
    draft = result.output

    assert draft.answerable is True
    tree = sqlglot.parse_one(draft.sql, read="postgres")  # raises if it does not parse
    assert isinstance(tree, exp.Query)

    tables = {f"{t.db}.{t.name}" for t in tree.find_all(exp.Table)}
    assert {"shop.orders", "shop.customers"} <= tables
    # The prompt's no-star rule (count(*) is fine: its Star sits inside a Count).
    stars = [s for s in tree.find_all(exp.Star) if not isinstance(s.parent, exp.Count)]
    assert stars == []
    assert result.usage.cost_usd is not None
