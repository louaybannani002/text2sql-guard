import pytest

from tests.pipeline.test_orchestrator import GOOD_SQL, POLICY, ROWS, FakeExecutor
from tests.support.fake_embedder import FakeEmbedder
from tests.support.fake_llm import llm_config
from text2sql.executor.errors import QueryTimeoutError
from text2sql.guard.sql_validator import Rejection, ValidatedSql
from text2sql.pipeline.deps import OrchestratorDeps
from text2sql.pipeline.feedback import describe_error
from text2sql.pipeline.run import RunState
from text2sql.pipeline.stages import execute_stage, validate_stage
from text2sql.pipeline.trace import Tracer


def _run() -> RunState:
    return RunState("q", Tracer(None, describe_error=describe_error))


def _deps(executor: FakeExecutor) -> OrchestratorDeps:
    return OrchestratorDeps(
        db=object(),  # type: ignore[arg-type]  # unused here
        llm=llm_config(),
        embed=FakeEmbedder(),
        policy=POLICY,
        executor=executor,
        token_budget=2500,
    )


async def test_valid_sql_becomes_the_run_sql() -> None:
    run = _run()
    validated = await validate_stage(run, _deps(FakeExecutor()), GOOD_SQL, 2, retryable=bool)
    assert isinstance(validated, ValidatedSql)
    assert run.sql == validated.sql
    (stage,) = run.tracer.trace().stages
    assert (stage.stage, stage.attempt, stage.status) == ("validate", 2, "ok")


@pytest.mark.parametrize("retry", [True, False])
async def test_rejection_is_recorded_with_the_callers_retry_policy(*, retry: bool) -> None:
    run = _run()
    seen: list[Rejection] = []

    def policy(rejection: Rejection) -> bool:
        seen.append(rejection)
        return retry

    result = await validate_stage(
        run, _deps(FakeExecutor()), "DELETE FROM shop.orders", 0, retryable=policy
    )
    assert isinstance(result, Rejection)
    assert seen == [result]
    assert run.sql is None
    (stage,) = run.tracer.trace().stages
    assert (stage.status, stage.error) == ("error", f"rejected:{result.rule}")


async def test_execute_records_the_result_summary() -> None:
    run = _run()
    deps = _deps(FakeExecutor(ROWS))
    validated = await validate_stage(run, deps, GOOD_SQL, 1, retryable=bool)
    assert isinstance(validated, ValidatedSql)
    assert await execute_stage(run, deps, validated, 1) == ROWS
    stage = run.tracer.trace().stages[-1]
    assert stage.output["row_count"] == 2


async def test_execution_errors_are_traced_and_raised() -> None:
    run = _run()
    deps = _deps(FakeExecutor(QueryTimeoutError("too slow")))
    validated = await validate_stage(run, deps, GOOD_SQL, 1, retryable=bool)
    assert isinstance(validated, ValidatedSql)
    with pytest.raises(QueryTimeoutError):
        await execute_stage(run, deps, validated, 1)
    assert run.tracer.trace().stages[-1].status == "error"
