"""Run the full pipeline over the datasets, with bounded concurrency."""

import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence

from text2sql.eval.compare import Comparison, compare_results
from text2sql.eval.datasets import Attack, BenignCase, GoldPair
from text2sql.eval.ordering import order_key_columns
from text2sql.eval.outcomes import (
    AttackOutcome,
    BenignOutcome,
    GoldOutcome,
    Usage,
    infrastructure_error,
    stopped_by,
)
from text2sql.eval.pipeline_setup import EvalPipeline
from text2sql.executor.errors import ExecutionError
from text2sql.executor.executor import QueryResult
from text2sql.guard.sql_validator import Rejection, validate
from text2sql.observability.logging import get_logger
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.orchestrator import answer as run_pipeline
from text2sql.pipeline.trace import Trace

log = get_logger(__name__)

QUESTION_TIMEOUT_S = 180.0
RETRY_DELAYS_S = (10.0, 30.0, 60.0)
BREAKER_THRESHOLD = 5


class CircuitBreaker:
    """Stops calling the provider after ``threshold`` questions in a row ended in outages.

    A dead API key or an exhausted quota would otherwise grind through every retry of every
    question. Once tripped, remaining questions fail at once as infrastructure errors.
    """

    def __init__(self, threshold: int = BREAKER_THRESHOLD) -> None:
        """Trip after ``threshold`` consecutive infrastructure errors."""
        self.threshold = threshold
        self.consecutive = 0
        self.tripped = False

    def record(self, *, outage: bool) -> None:
        """Count one finished question."""
        self.consecutive = self.consecutive + 1 if outage else 0
        self.tripped = self.tripped or self.consecutive >= self.threshold


SAMPLE_ROWS = 5
type AnswerFn = Callable[[str], Awaitable[Answer]]


def _skipped(question: str, reason: str) -> Answer:
    return Answer(
        question=question,
        status="failed",
        message="The evaluation could not run this question.",
        detail=reason,
        sql=None,
        attempts=0,
        trace=Trace(stages=[], total_ms=0.0),
    )


def pipeline_answer(
    pipeline: EvalPipeline,
    *,
    retry_delays_s: Sequence[float] = RETRY_DELAYS_S,
    breaker: CircuitBreaker | None = None,
) -> AnswerFn:
    """The orchestrator bound to ``pipeline``.

    Infrastructure errors (rate limits, provider outages) are retried after each delay in
    ``retry_delays_s``; a crash becomes a ``failed`` Answer with an empty trace.
    """

    async def once(question: str) -> Answer:
        try:
            async with asyncio.timeout(QUESTION_TIMEOUT_S):
                return await run_pipeline(question, pipeline.deps)
        except Exception as exc:  # noqa: BLE001 - one bad question must not stop the run
            log.warning("eval_question_crashed", error=type(exc).__name__)
            return _skipped(question, f"{type(exc).__name__}: {exc}")

    async def answer(question: str) -> Answer:
        if breaker is not None and breaker.tripped:
            return _skipped(question, "skipped: the model provider kept failing")
        result = await once(question)
        for delay in retry_delays_s:
            if not infrastructure_error(result) or (breaker is not None and breaker.tripped):
                break
            log.warning("eval_retry_after_infrastructure_error", delay_s=delay)
            await asyncio.sleep(delay)
            result = await once(question)
        if breaker is not None:
            breaker.record(outage=infrastructure_error(result))
        return result

    return answer


class Progress:
    """One line per finished question on stderr, so long runs show where they are."""

    def __init__(self, dataset: str, total: int) -> None:
        """Count ``total`` questions of ``dataset``."""
        self.dataset = dataset
        self.total = total
        self.done = 0

    def report(self, question_id: str, outcome: str, total_ms: float) -> None:
        """Print ``[gold 12/150] sales-easy-03 correct (3.2 s)``."""
        self.done += 1
        seconds = f"{total_ms / 1000:.1f} s"
        line = f"[{self.dataset} {self.done}/{self.total}] {question_id} {outcome} ({seconds})"
        print(line, file=sys.stderr, flush=True)  # noqa: T201 - command-line progress


async def gather_limited[T](
    items: Sequence[T], work: Callable[[T], Awaitable[object]], concurrency: int
) -> list[object]:
    """``work`` on every item, at most ``concurrency`` at a time, results in input order."""
    limit = asyncio.Semaphore(concurrency)

    async def one(item: T) -> object:
        async with limit:
            return await work(item)

    return list(await asyncio.gather(*(one(item) for item in items)))


class GoldSqlError(Exception):
    """A gold SQL no longer passes the validator or fails to execute: fix the dataset."""


async def gold_result(pipeline: EvalPipeline, pair: GoldPair) -> QueryResult:
    """Execute the gold SQL under the same validator and executor limits as predictions."""
    validated = validate(pair.sql, pipeline.policy)
    if isinstance(validated, Rejection):
        msg = f"gold SQL of {pair.id} is rejected: {validated.rule}"
        raise GoldSqlError(msg)
    return await pipeline.executor.execute(validated)


def judge(pair: GoldPair, gold: QueryResult, answer: Answer) -> GoldOutcome:
    """Compare the pipeline's answer with the gold result."""
    predicted = answer.result
    if answer.status != "answered" or predicted is None:
        comparison = Comparison(match=False, reason=f"status {answer.status}")
    else:
        names = [c.name for c in gold.columns]
        comparison = compare_results(
            gold.rows,
            predicted.rows,
            order_keys=order_key_columns(pair.sql),
            optional_columns=[names.index(c) for c in pair.optional_columns if c in names],
        )
    return GoldOutcome(
        id=pair.id,
        category=pair.category,
        difficulty=pair.difficulty,
        question=pair.question,
        status=answer.status,
        correct=comparison.match,
        reason=comparison.reason,
        predicted_sql=answer.sql,
        gold_sql=pair.sql,
        usage=Usage.of(answer),
        message=answer.message,
        detail=answer.detail,
        infra_error=infrastructure_error(answer),
        predicted_columns=[c.name for c in predicted.columns] if predicted else [],
        predicted_sample=predicted.rows[:SAMPLE_ROWS] if predicted else [],
        gold_columns=[c.name for c in gold.columns],
        gold_sample=gold.rows[:SAMPLE_ROWS],
    )


async def run_gold(
    pipeline: EvalPipeline, answer: AnswerFn, pairs: Sequence[GoldPair], concurrency: int
) -> list[GoldOutcome]:
    """Every gold question through the pipeline, judged against its gold result."""
    progress = Progress("gold", len(pairs))

    async def one(pair: GoldPair) -> GoldOutcome:
        try:
            gold = await gold_result(pipeline, pair)
        except ExecutionError as exc:
            msg = f"gold SQL of {pair.id} failed to execute: {type(exc).__name__}"
            raise GoldSqlError(msg) from exc
        outcome = judge(pair, gold, await answer(pair.question))
        label = "correct" if outcome.correct else f"wrong: {outcome.reason}"
        progress.report(pair.id, label, outcome.usage.total_ms)
        return outcome

    return [o for o in await gather_limited(pairs, one, concurrency) if isinstance(o, GoldOutcome)]


async def run_attacks(
    answer: AnswerFn, attacks: Sequence[Attack], concurrency: int
) -> list[AttackOutcome]:
    """Every attack through the pipeline; records which layer stopped it."""
    progress = Progress("adversarial", len(attacks))

    async def one(attack: Attack) -> AttackOutcome:
        result = await answer(attack.question)
        progress.report(attack.id, f"stopped by {stopped_by(result)}", result.trace.total_ms)
        return AttackOutcome(
            id=attack.id,
            category=attack.category,
            technique=attack.technique,
            expected_layer=attack.expected_layer,
            status=result.status,
            stopped_by=stopped_by(result),
            usage=Usage.of(result),
            predicted_sql=result.sql if result.status == "answered" else None,
            infra_error=infrastructure_error(result),
        )

    outcomes = await gather_limited(attacks, one, concurrency)
    return [o for o in outcomes if isinstance(o, AttackOutcome)]


async def run_benign(
    answer: AnswerFn, cases: Sequence[BenignCase], concurrency: int
) -> list[BenignOutcome]:
    """Every benign-but-suspicious question through the pipeline."""
    progress = Progress("benign", len(cases))

    async def one(case: BenignCase) -> BenignOutcome:
        result = await answer(case.question)
        progress.report(case.id, result.status, result.trace.total_ms)
        return BenignOutcome(
            id=case.id,
            expected_status=case.expected_status,
            known_false_block=case.known_false_block,
            status=result.status,
            stopped_by=stopped_by(result),
            usage=Usage.of(result),
            infra_error=infrastructure_error(result),
        )

    outcomes = await gather_limited(cases, one, concurrency)
    return [o for o in outcomes if isinstance(o, BenignOutcome)]
