import asyncpg
import pytest
from asyncpg import exceptions as pg

from text2sql.executor.errors import (
    DatabaseUnavailableError,
    ExecutionError,
    QueryDataError,
    QueryInvalidError,
    QueryPermissionError,
    QueryReadOnlyError,
    QueryTimeoutError,
    map_database_error,
)


@pytest.mark.parametrize(
    ("raised", "expected", "sqlstate"),
    [
        (pg.QueryCanceledError("canceling statement"), QueryTimeoutError, "57014"),
        (pg.InsufficientPrivilegeError("permission denied"), QueryPermissionError, "42501"),
        (pg.ReadOnlySQLTransactionError("read-only"), QueryReadOnlyError, "25006"),
        (pg.PostgresSyntaxError("syntax error"), QueryInvalidError, "42601"),
        (pg.UndefinedColumnError("no column"), QueryInvalidError, "42703"),
        (pg.UndefinedTableError("no table"), QueryInvalidError, "42P01"),
        (pg.UndefinedFunctionError("no function"), QueryInvalidError, "42883"),
        (pg.DivisionByZeroError("division by zero"), QueryDataError, "22012"),
        (pg.InvalidDatetimeFormatError("bad date"), QueryDataError, "22007"),
        (pg.TooManyConnectionsError("too many"), DatabaseUnavailableError, "53300"),
        (pg.AdminShutdownError("shutdown"), DatabaseUnavailableError, "57P01"),
        (pg.DeadlockDetectedError("deadlock"), ExecutionError, "40P01"),
    ],
)
def test_postgres_errors_map_by_sqlstate(
    raised: Exception, expected: type[ExecutionError], sqlstate: str
) -> None:
    error = map_database_error(raised)
    assert type(error) is expected
    assert error.sqlstate == sqlstate


@pytest.mark.parametrize(
    "raised",
    [
        ConnectionRefusedError("refused"),
        OSError("network down"),
        TimeoutError(),  # e.g. waiting for a pool connection
        asyncpg.ConnectionDoesNotExistError("connection was closed"),
    ],
)
def test_connection_problems_mean_unavailable(raised: BaseException) -> None:
    assert isinstance(map_database_error(raised), DatabaseUnavailableError)


def test_client_misuse_is_not_reported_as_an_outage() -> None:
    error = map_database_error(asyncpg.InterfaceError("cannot use cursor outside transaction"))
    assert type(error) is ExecutionError


def test_unknown_exceptions_are_wrapped_without_details() -> None:
    error = map_database_error(KeyError("secret internal detail"))
    assert type(error) is ExecutionError
    assert "secret" not in str(error)


def test_execution_errors_pass_through() -> None:
    original = QueryTimeoutError("slow")
    assert map_database_error(original) is original


def test_permission_message_keeps_the_database_reason() -> None:
    error = map_database_error(pg.InsufficientPrivilegeError("permission denied for table x"))
    assert "permission denied for table x" in str(error)
