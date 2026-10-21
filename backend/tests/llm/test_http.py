import dataclasses
import json
from collections.abc import Callable

from pydantic import BaseModel

from tests.support.fake_llm import FakeCompletion, llm_config, model_response
from text2sql.llm import generate_structured
from text2sql.llm._litellm import litellm
from text2sql.llm.http import open_http_session


class Answer(BaseModel):
    ok: bool


async def test_session_has_a_bounded_keepalive_pool() -> None:
    session = open_http_session(7)
    try:
        assert session.connector is not None
        assert session.connector.limit == 7
    finally:
        await session.close()


async def test_every_completion_gets_the_shared_session(
    fake_llm: Callable[..., FakeCompletion],
) -> None:
    completion = fake_llm(model_response(json.dumps({"ok": True})))
    session = open_http_session(2)
    try:
        config = dataclasses.replace(llm_config(), http_session=session)
        await generate_structured([{"role": "user", "content": "x"}], Answer, "fast", config=config)
    finally:
        await session.close()
    assert completion.calls[0]["shared_session"] is session


async def test_cached_prompt_tokens_are_recorded(fake_llm: Callable[..., FakeCompletion]) -> None:
    response = litellm.ModelResponse(
        model="gpt-5.4-mini",
        choices=[{"message": {"role": "assistant", "content": json.dumps({"ok": True})}}],
        usage={
            "prompt_tokens": 3000,
            "completion_tokens": 10,
            "total_tokens": 3010,
            "prompt_tokens_details": {"cached_tokens": 2048},
        },
    )
    fake_llm(response)
    result = await generate_structured(
        [{"role": "user", "content": "x"}], Answer, "fast", config=llm_config()
    )
    assert result.usage.cached_tokens == 2048
