"""Internal error types for query execution, and the mapping from database errors.

Callers catch ``ExecutionError``; subclasses say what went wrong in terms the pipeline can act
on (retry, repair the SQL, tell the user). Messages are safe to show: they never contain rows.
"""

import asyncpg

# Network-level failures. Other asyncpg InterfaceErrors are client misuse, not an outage.
_UNREACHABLE: tuple[type[BaseException], ...] = (
    asyncpg.PostgresConnectionError,
    asyncpg.ConnectionDoesNotExistError,
    ConnectionError,
    OSError,
)


class ExecutionError(Exception):
    """Base class: the query could not be executed."""

    def __init__(self, message: str, *, sqlstate: str | None = None) -> None:
        """Keep the Postgres SQLSTATE (if any) for logs and metrics."""
        super().__init__(message)
        self.sqlstate = sqlstate


class QueryTimeoutError(ExecutionError):
    """The statement exceeded the statement timeout and was cancelled."""


class QueryTooExpensiveError(ExecutionError):
    """EXPLAIN estimates exceed the configured cost or row thresholds; nothing was run."""

    def __init__(self, message: str, *, estimated_cost: float, estimated_rows: int) -> None:
        """Carry the estimates so the caller can report or log them."""
        super().__init__(message)
        self.estimated_cost = estimated_cost
        self.estimated_rows = estimated_rows


class QueryPermissionError(ExecutionError):
    """The query role may not read something the query references."""


class QueryReadOnlyError(ExecutionError):
    """The query tried to write inside the read-only transaction."""


class QueryInvalidError(ExecutionError):
    """The SQL is wrong: syntax, unknown table/column/function, type mismatch."""


class QueryDataError(ExecutionError):
    """The SQL is valid but failed on the data (division by zero, bad cast, overflow)."""


class DatabaseUnavailableError(ExecutionError):
    """The database could not be reached or refused the connection; worth retrying later."""


def map_database_error(exc: BaseException) -> ExecutionError:
    """Translate an asyncpg/network exception into an ``ExecutionError`` subclass."""
    if isinstance(exc, ExecutionError):
        return exc
    if isinstance(exc, asyncpg.PostgresError):
        state = exc.sqlstate or ""
        message = str(exc)
        mapping: list[tuple[bool, type[ExecutionError], str]] = [
            (state == "57014", QueryTimeoutError, "The query took too long and was cancelled."),
            (state == "42501", QueryPermissionError, f"Not allowed: {message}"),
            (state == "25006", QueryReadOnlyError, "The query tried to modify data."),
            (state.startswith("42"), QueryInvalidError, f"Invalid query: {message}"),
            (state.startswith("22"), QueryDataError, f"The query failed on the data: {message}"),
            (
                state.startswith(("08", "53", "57P")),
                DatabaseUnavailableError,
                "The database is unavailable.",
            ),
        ]
        for matches, error_type, text in mapping:
            if matches:
                return error_type(text, sqlstate=state)
        return ExecutionError(f"The database rejected the query: {message}", sqlstate=state)
    if isinstance(exc, (*_UNREACHABLE, TimeoutError)):
        return DatabaseUnavailableError("The database is unavailable.")
    return ExecutionError(f"Unexpected execution failure: {type(exc).__name__}")
