import io
import json
import logging
import sys
from collections.abc import Iterator

import pytest
import structlog

from text2sql.observability.logging import REDACTED, bind_user, configure_logging, get_logger


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    structlog.reset_defaults()
    root.handlers[:], root.level = handlers, level


def test_emits_json_lines(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True)
    get_logger("test").info("hello", answer=42)
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["event"] == "hello"
    assert record["answer"] == 42
    assert record["level"] == "info"
    assert "timestamp" in record


def test_writes_to_current_stdout_not_the_one_at_configure_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at_configure, later = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", at_configure)
    configure_logging("INFO", json=True)
    monkeypatch.setattr(sys, "stdout", later)  # e.g. a test's capture stream being closed
    get_logger("test").info("after_swap")
    assert "after_swap" in later.getvalue()
    assert at_configure.getvalue() == ""


def _last_line(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    record: dict[str, object] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    return record


@pytest.mark.parametrize(
    "key",
    ["question", "sql", "rows", "prompt", "api_key", "password", "groq_api_key", "redis_url"],
)
def test_sensitive_values_are_redacted(key: str, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True)
    get_logger("test").info("oops", **{key: "SELECT secret FROM somewhere"})
    record = _last_line(capsys)
    assert record[key] == REDACTED
    assert "SELECT secret" not in json.dumps(record)


@pytest.mark.parametrize("key", ["tokens", "total_tokens", "row_count", "prompt_version"])
def test_harmless_keys_are_kept(key: str, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True)
    get_logger("test").info("fine", **{key: 7})
    assert _last_line(capsys)[key] == 7


def test_bound_user_appears_on_every_line(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True)
    with structlog.contextvars.bound_contextvars(request_id="r-1", user_id=None):
        bind_user("demo")
        get_logger("test").info("one")
        record = _last_line(capsys)
    assert (record["request_id"], record["user_id"]) == ("r-1", "demo")
    get_logger("test").info("outside")
    assert "user_id" not in _last_line(capsys)
