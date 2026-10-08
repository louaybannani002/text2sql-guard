import pytest

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
from text2sql.llm import LLMProviderError
from text2sql.pipeline.feedback import (
    describe_error,
    execution_feedback,
    is_fixable_execution_error,
    is_security_execution_error,
    rejection_feedback,
    user_message,
)
from text2sql.retrieval.retriever import CatalogNotBuiltError


@pytest.mark.parametrize(
    ("error", "fixable", "security"),
    [
        (QueryInvalidError("Invalid query: column o.status does not exist"), True, False),
        (QueryDataError("division by zero"), True, False),
        (QueryPermissionError("permission denied"), False, True),
        (QueryReadOnlyError("read-only"), False, True),
        (QueryTimeoutError("slow"), False, False),
        (QueryTooExpensiveError("big", estimated_cost=1e9, estimated_rows=1), False, False),
        (DatabaseUnavailableError("down"), False, False),
    ],
)
def test_execution_error_classes(
    error: ExecutionError,
    fixable: bool,  # noqa: FBT001
    security: bool,  # noqa: FBT001
) -> None:
    assert is_fixable_execution_error(error) is fixable
    assert is_security_execution_error(error) is security


def test_feedback_texts() -> None:
    rejection = Rejection("columns", "Unknown column shop.orders.status.", [], security=False)
    assert rejection_feedback(rejection) == (
        "validator rule 'columns': Unknown column shop.orders.status."
    )
    error = QueryInvalidError("Invalid query: operator does not exist: timestamp > integer")
    assert execution_feedback(error) == (
        "database error (QueryInvalidError): "
        "Invalid query: operator does not exist: timestamp > integer"
    )


@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        (QueryTimeoutError("57014"), "took too long"),
        (CatalogNotBuiltError("empty"), "catalog is not ready"),
        (
            LLMProviderError("x", role="main", model="m", attempts=3, status_code=503),
            "assistant is unavailable",
        ),
        (KeyError("internal detail"), "Something went wrong"),
    ],
)
def test_user_messages_hide_internals(error: BaseException, fragment: str) -> None:
    message = user_message(error)
    assert fragment in message
    assert "internal detail" not in message


def test_describe_error_marks_only_fixable_execution_errors_retryable() -> None:
    assert describe_error(QueryInvalidError("bad"))[2] is True
    assert describe_error(QueryTimeoutError("slow"))[2] is False
    assert describe_error(CatalogNotBuiltError("x")) == (
        "CatalogNotBuiltError",
        "The data catalog is not ready yet. Please try again later.",
        False,
    )
