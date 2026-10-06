import io
import json
import logging
import sys
from collections.abc import Iterator

import pytest
import structlog

from text2sql.observability.logging import configure_logging, get_logger


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
