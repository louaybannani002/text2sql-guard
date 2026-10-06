import json

import pytest

from text2sql.observability.logging import configure_logging, get_logger


def test_emits_json_lines(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True)
    get_logger("test").info("hello", answer=42)
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["event"] == "hello"
    assert record["answer"] == 42
    assert record["level"] == "info"
    assert "timestamp" in record
