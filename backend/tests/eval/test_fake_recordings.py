from importlib.resources import files

from text2sql.eval.fake_recordings import build, render
from text2sql.llm.fake import RECORDINGS


def test_committed_recordings_are_up_to_date() -> None:
    # Regenerate with: uv run python -m text2sql.eval.fake_recordings
    committed = files("text2sql.llm").joinpath(RECORDINGS).read_text(encoding="utf-8")
    assert committed == render(build())


def test_recordings_cover_gold_and_examples() -> None:
    recorded = build()
    assert len(recorded) >= 150
    assert all(sql and not sql.endswith(";") for sql in recorded.values())
