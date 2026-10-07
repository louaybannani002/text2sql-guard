from typing import Any

import pytest
from pydantic import SecretStr

from text2sql.config.settings import Settings
from text2sql.executor import executor as executor_module
from text2sql.executor.executor import ExecutionLimits, QueryExecutor

# Query behaviour is tested against a real Postgres in test_executor.py (Testcontainers).


def test_limits_from_settings(settings: Settings) -> None:
    assert ExecutionLimits.from_settings(settings) == ExecutionLimits(
        statement_timeout_ms=5000, max_cost=1_000_000.0, max_plan_rows=10_000_000, max_rows=1000
    )


async def test_create_opens_a_reader_pool(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_create_pool(url: SecretStr, **kwargs: Any) -> object:  # noqa: ANN401
        calls.append({"url": url.get_secret_value(), **kwargs})
        return object()

    monkeypatch.setattr(executor_module, "create_pool", fake_create_pool)
    executor = await QueryExecutor.create(settings)

    assert calls[0]["url"].startswith("postgresql+asyncpg://t2s_reader:")
    assert (calls[0]["min_size"], calls[0]["max_size"]) == (1, 5)
    assert executor.limits.max_rows == 1000
