"""The traced validate and execute stages, shared by the repair loop and the cache path."""

from collections.abc import Callable

from text2sql.executor.executor import QueryResult
from text2sql.guard.sql_validator import Rejection, ValidatedSql, validate
from text2sql.pipeline.deps import OrchestratorDeps
from text2sql.pipeline.run import RunState


async def validate_stage(
    run: RunState,
    deps: OrchestratorDeps,
    sql: str,
    attempt: int,
    *,
    retryable: Callable[[Rejection], bool],
) -> ValidatedSql | Rejection:
    """Validate ``sql`` against the policy; on success it becomes ``run.sql``."""
    async with run.tracer.stage("validate", attempt, {"sql_chars": len(sql)}) as stage:
        validation = validate(sql, deps.policy)
        if isinstance(validation, Rejection):
            stage.output = {
                "valid": False,
                "rule": validation.rule,
                "security": validation.security,
            }
            stage.fail(
                f"rejected:{validation.rule}", validation.reason, retryable=retryable(validation)
            )
        else:
            run.sql = validation.sql
            stage.output = {
                "valid": True,
                "tables": list(validation.tables),
                "rewrites": list(validation.rewrites),
            }
    return validation


async def execute_stage(
    run: RunState, deps: OrchestratorDeps, validated: ValidatedSql, attempt: int
) -> QueryResult:
    """Execute validated SQL; ``ExecutionError`` is recorded in the trace and re-raised."""
    async with run.tracer.stage("execute", attempt, {"tables": list(validated.tables)}) as stage:
        result = await deps.executor.execute(validated)
        stage.output = {
            "row_count": result.row_count,
            "truncated": result.truncated,
            "execution_ms": result.execution_ms,
            "estimated_cost": result.estimated_cost,
        }
    return result
