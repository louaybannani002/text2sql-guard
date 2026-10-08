"""The repair loop: generate SQL, validate it, execute it; retry fixable failures."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from text2sql.executor.errors import ExecutionError
from text2sql.guard.sql_validator import Rejection
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
from text2sql.pipeline.stages import execute_stage, validate_stage
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

        validation = await validate_stage(
            run, deps, draft.sql, attempt, retryable=_retry_policy(last=attempt == max_attempts)
        )
        if isinstance(validation, Rejection):
            if validation.security:
                return run.finish("rejected", f"I can't run that query: {validation.reason}")
            failures.append(FailedAttempt(draft.sql, rejection_feedback(validation)))
            continue

        try:
            result = await execute_stage(run, deps, validation, attempt)
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


def _retry_policy(*, last: bool) -> Callable[[Rejection], bool]:
    """Rejections the loop will retry: not security ones, and not on the last attempt."""
    return lambda rejection: not rejection.security and not last


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
