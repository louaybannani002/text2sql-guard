"""The repair loop: generate SQL, validate it, execute it; retry fixable failures."""

from typing import TYPE_CHECKING

from text2sql.executor.errors import ExecutionError
from text2sql.guard.sql_validator import Rejection, validate
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.deps import OrchestratorDeps
from text2sql.pipeline.feedback import (
    execution_feedback,
    is_fixable_execution_error,
    is_security_execution_error,
    rejection_feedback,
    user_message,
)
from text2sql.pipeline.generate import FailedAttempt, SqlDraft, generate_sql
from text2sql.pipeline.run import RunState
from text2sql.retrieval.context import SchemaContext

if TYPE_CHECKING:
    from text2sql.executor.serialize import JsonValue


async def generate_validate_execute(
    run: RunState, deps: OrchestratorDeps, context: SchemaContext
) -> Answer:
    """Up to ``deps.max_retries + 1`` attempts; security rejections end the run at once."""
    failures: list[FailedAttempt] = []
    max_attempts = deps.max_retries + 1
    while run.attempts < max_attempts:
        run.attempts += 1
        attempt = run.attempts
        draft = await _generate(run, deps, context, failures)
        if not draft.answerable:
            message = f"Sorry, I can't answer that with the available data. {draft.explanation}"
            return run.finish("cannot_answer", message.strip())

        last_attempt = attempt == max_attempts
        async with run.tracer.stage("validate", attempt, {"sql_chars": len(draft.sql)}) as stage:
            validation = validate(draft.sql, deps.policy)
            if isinstance(validation, Rejection):
                stage.output = {
                    "valid": False,
                    "rule": validation.rule,
                    "security": validation.security,
                }
                stage.fail(
                    f"rejected:{validation.rule}",
                    validation.reason,
                    retryable=not validation.security and not last_attempt,
                )
            else:
                run.sql = validation.sql
                stage.output = {
                    "valid": True,
                    "tables": list(validation.tables),
                    "rewrites": list(validation.rewrites),
                }
        if isinstance(validation, Rejection):
            if validation.security:
                return run.finish("rejected", f"I can't run that query: {validation.reason}")
            failures.append(FailedAttempt(draft.sql, rejection_feedback(validation)))
            continue

        try:
            async with run.tracer.stage(
                "execute", attempt, {"tables": list(validation.tables)}
            ) as stage:
                result = await deps.executor.execute(validation)
                stage.output = {
                    "row_count": result.row_count,
                    "truncated": result.truncated,
                    "execution_ms": result.execution_ms,
                    "estimated_cost": result.estimated_cost,
                }
        except ExecutionError as error:
            if is_security_execution_error(error):
                return run.finish(
                    "rejected", f"I can't run that query: {user_message(error)}", detail=str(error)
                )
            if not is_fixable_execution_error(error):
                return run.finish("failed", user_message(error), detail=str(error))
            # The model sees its own SQL, not the normalised one (formatting, added LIMIT).
            failures.append(FailedAttempt(draft.sql, execution_feedback(error)))
            continue
        return run.finish("answered", draft.explanation, result)

    last = failures[-1].error if failures else "unknown error"
    message = (
        f"I couldn't produce a working query after {run.attempts} attempts. "
        "Try rephrasing the question."
    )
    return run.finish("failed", message, detail=f"last error: {last}")


async def _generate(
    run: RunState, deps: OrchestratorDeps, context: SchemaContext, failures: list[FailedAttempt]
) -> SqlDraft:
    stage_input: dict[str, JsonValue] = {
        "context_tokens": context.tokens,
        "examples": len(context.examples),
        "previous_failures": len(failures),
    }
    async with run.tracer.stage("generate", run.attempts, stage_input) as stage:
        generated = await generate_sql(
            run.question,
            context.text,
            context.examples,
            previous_attempts=failures,
            config=deps.llm,
        )
        draft = generated.output
        stage.usage.append(generated.usage)
        stage.output = {
            "answerable": draft.answerable,
            "confidence": draft.confidence,
            "tables_used": list(draft.tables_used),
            "sql": draft.sql,
        }
    run.draft = draft
    run.sql = draft.sql or run.sql
    return draft
