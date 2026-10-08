import sys

import pytest

from text2sql.llm import warmup
from text2sql.llm._litellm import litellm


async def test_warm_up_loads_the_sdk_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_acompletion(**kwargs: object) -> object:
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    elapsed = await warmup.warm_up("openai/gpt-5.4-mini")

    assert elapsed >= 0
    assert "openai" in sys.modules
    (call,) = calls
    assert call["mock_response"] == "ok"  # LiteLLM answers locally, nothing is sent
    assert call["model"] == "openai/gpt-5.4-mini"
    assert call["api_key"] == warmup._FAKE_KEY  # noqa: SLF001 - never a real key


async def test_mocked_litellm_call_needs_no_network() -> None:
    # The real LiteLLM mock path: would raise if it tried to reach a provider with a fake key.
    assert await warmup.warm_up("openai/gpt-5.4-mini") >= 0
