"""The LLM classifier and schema retrieval run concurrently; generation waits for the verdict.

Synchronised with events rather than timings, so the tests are deterministic.
"""

import asyncio
from collections.abc import Callable

import pytest

from tests.pipeline.test_orchestrator import QUESTION, ROWS, FakeExecutor, _answer, _draft
from tests.support.fake_llm import FakeCompletion
from text2sql.guard.input_guard import InputVerdict
from text2sql.llm.types import Usage
from text2sql.pipeline import orchestrator
from text2sql.retrieval.context import SchemaContext
from text2sql.retrieval.retriever import CatalogNotBuiltError

ALLOWED = InputVerdict(allowed=True, category="data_question", reason="ok", layer="classifier")
BLOCKED = InputVerdict(
    allowed=False, category="off_topic", reason="Only marketplace data.", layer="classifier"
)
USAGE = Usage(
    role="embedding",
    model="openai/text-embedding-3-small",
    prompt_tokens=9,
    completion_tokens=0,
    total_tokens=9,
    latency_ms=1.0,
    cost_usd=0.0,
    attempts=1,
)


class Probe:
    """Fake classify / retrieve that can wait for each other and record cancellation."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.retrieval_started = asyncio.Event()
        self.classifier_started = asyncio.Event()
        self.cancelled: list[str] = []
        self.verdict = ALLOWED
        self.classify_waits_for_retrieval = False
        self.classify_hangs = False
        self.retrieve_hangs = False
        self.retrieve_error: Exception | None = None
        monkeypatch.setattr(orchestrator, "classify", self.classify)
        monkeypatch.setattr(orchestrator, "retrieve", self.retrieve)

    async def classify(self, question: str, **_kwargs: object) -> InputVerdict:
        del question
        self.classifier_started.set()
        try:
            if self.classify_waits_for_retrieval:
                await asyncio.wait_for(self.retrieval_started.wait(), timeout=2)
            if self.classify_hangs:
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.append("classify")
            raise
        return self.verdict

    async def retrieve(self, question: str, k: int, **_kwargs: object) -> SchemaContext:
        del k
        self.retrieval_started.set()
        try:
            if self.retrieve_hangs:
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.append("retrieve")
            raise
        if self.retrieve_error is not None:
            raise self.retrieve_error
        return SchemaContext(
            question=question,
            tables=[],
            examples=[],
            text="CREATE TABLE shop.orders (order_status text);",
            tokens=12,
            token_budget=2500,
            usage=USAGE,
        )


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Probe:
    return Probe(monkeypatch)


async def test_classifier_and_retrieval_overlap(
    probe: Probe, fake_llm: Callable[..., FakeCompletion]
) -> None:
    # The classifier only returns once retrieval has started: sequential code would time out.
    probe.classify_waits_for_retrieval = True
    fake_llm(_draft())
    result = await _answer(FakeExecutor(ROWS))
    assert result.status == "answered"
    assert {"input_guard", "retrieve", "generate"} <= {s.stage for s in result.trace.stages}


async def test_a_block_cancels_retrieval_and_never_generates(
    probe: Probe, fake_llm: Callable[..., FakeCompletion]
) -> None:
    probe.verdict = BLOCKED
    probe.retrieve_hangs = True
    completion = fake_llm()
    result = await _answer(FakeExecutor())
    assert (result.status, result.message) == ("blocked", "Only marketplace data.")
    assert probe.cancelled == ["retrieve"]
    assert completion.calls == []  # the generator was never called


async def test_a_retrieval_failure_does_not_hide_a_block(probe: Probe) -> None:
    probe.verdict = BLOCKED
    probe.retrieve_error = CatalogNotBuiltError("no catalog")
    result = await _answer(FakeExecutor())
    assert result.status == "blocked"


async def test_a_retrieval_failure_fails_an_allowed_question(probe: Probe) -> None:
    probe.retrieve_error = CatalogNotBuiltError("no catalog")
    result = await _answer(FakeExecutor())
    assert result.status == "failed"


async def test_cancelling_the_request_cancels_both(probe: Probe) -> None:
    probe.classify_hangs = True
    probe.retrieve_hangs = True
    task = asyncio.create_task(_answer(FakeExecutor(), QUESTION))
    await asyncio.wait_for(probe.retrieval_started.wait(), timeout=2)
    await asyncio.wait_for(probe.classifier_started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sorted(probe.cancelled) == ["classify", "retrieve"]
