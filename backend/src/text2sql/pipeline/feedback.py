"""Which failures the generator may fix, and how to describe failures to it and to users.

Fixable: the query is wrong (unknown column, syntax, type mismatch, bad value). Never fixable:
security rejections (the query tried something forbidden; asking for a "fix" would invite the
model to look for a way around the rule) and operational failures (timeout, cost, outage).
"""

from text2sql.executor.errors import (
    DatabaseUnavailableError,
    ExecutionError,
    QueryDataError,
    QueryInvalidError,
    QueryPermissionError,
    QueryReadOnlyError,
    QueryTimeoutError,
    QueryTooExpensiveError,
)
from text2sql.guard.sql_validator import Rejection
from text2sql.llm import LLMError, LLMOutputValidationError
from text2sql.retrieval.retriever import CatalogNotBuiltError


def is_fixable_execution_error(error: ExecutionError) -> bool:
    """Wrong SQL the model can correct: invalid SQL (incl. type mismatch) or bad data use."""
    return isinstance(error, QueryInvalidError | QueryDataError)


def is_security_execution_error(error: ExecutionError) -> bool:
    """The database itself refused for privilege or read-only reasons."""
    return isinstance(error, QueryPermissionError | QueryReadOnlyError)


def rejection_feedback(rejection: Rejection) -> str:
    """How a validator rejection is reported back to the generator."""
    return f"validator rule '{rejection.rule}': {rejection.reason}"


def execution_feedback(error: ExecutionError) -> str:
    """How a database error is reported back to the generator."""
    return f"database error ({type(error).__name__}): {error}"


_USER_MESSAGES: list[tuple[type[BaseException], str]] = [
    (
        QueryTimeoutError,
        "The query took too long. Try a narrower question (fewer months, a filter).",
    ),
    (QueryTooExpensiveError, "That question needs too heavy a query. Try narrowing it down."),
    (DatabaseUnavailableError, "The database is unavailable right now. Please try again later."),
    (CatalogNotBuiltError, "The data catalog is not ready yet. Please try again later."),
    (LLMOutputValidationError, "The assistant produced an unusable answer. Please try again."),
    (LLMError, "The assistant is unavailable right now. Please try again later."),
]


def user_message(error: BaseException) -> str:
    """A plain-language message for a technical failure (never internal details)."""
    for error_type, message in _USER_MESSAGES:
        if isinstance(error, error_type):
            return message
    return "Something went wrong while answering. Please try again."


def describe_error(error: BaseException) -> tuple[str, str, bool]:
    """(error kind, user message, retryable) for stage error events."""
    retryable = isinstance(error, ExecutionError) and is_fixable_execution_error(error)
    message = str(error) if isinstance(error, ExecutionError) else user_message(error)
    return type(error).__name__, message, retryable
