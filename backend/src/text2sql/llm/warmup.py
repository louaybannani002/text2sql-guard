"""Load LiteLLM's lazily imported provider code at startup, not inside the first request.

LiteLLM imports and builds the OpenAI SDK client (thousands of pydantic models) on its first
call. Imports are synchronous, so that first call froze the event loop, and every other
request with it: seconds normally, minutes on a starved container. The API runs this once
before it reports healthy.
"""

import asyncio
import time

from text2sql.llm._litellm import litellm
from text2sql.observability.logging import get_logger

log = get_logger(__name__)

_FAKE_KEY = "warm-up-not-a-real-key"  # never sent: the call below is mocked


def _import_provider_sdk() -> None:
    import openai  # noqa: PLC0415 - the point is to pay for this import here

    openai.AsyncOpenAI(api_key=_FAKE_KEY)


async def warm_up(model: str) -> float:
    """Import the SDK (in a thread) and run one network-free LiteLLM call; returns ms."""
    started = time.perf_counter()
    await asyncio.to_thread(_import_provider_sdk)
    await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": "warm-up"}],
        mock_response="ok",  # LiteLLM answers locally: no request leaves the process
        api_key=_FAKE_KEY,
    )
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    log.info("llm_warmed_up", model=model, duration_ms=elapsed)
    return elapsed
