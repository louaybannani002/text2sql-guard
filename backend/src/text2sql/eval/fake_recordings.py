"""Build ``llm/fake_recordings.json``: the SQL the fake LLM mode answers with.

Every gold question and few-shot example maps (by normalised question) to its reviewed SQL, so
a load test over those questions runs realistic queries. Regenerate after changing the gold set
or the examples (a test fails when the file is out of date):

    uv run python -m text2sql.eval.fake_recordings
"""

import json
from importlib.resources import files
from pathlib import Path

from text2sql.cache.keys import normalize_question
from text2sql.eval.datasets import load_gold
from text2sql.llm.fake import RECORDINGS
from text2sql.retrieval.examples import load_examples

SEEDS = Path(__file__).resolve().parents[3] / "db" / "seeds" / "examples.toml"


def build() -> dict[str, str]:
    """Normalised question -> SQL, gold first then examples, sorted for stable diffs."""
    pairs = [(g.question, g.sql) for g in load_gold()]
    pairs += [(e.question, e.sql) for e in load_examples(SEEDS)]
    recorded: dict[str, str] = {}
    for question, sql in pairs:
        recorded.setdefault(normalize_question(question), sql.strip().rstrip(";"))
    return dict(sorted(recorded.items()))


def render(recorded: dict[str, str]) -> str:
    """The file's exact content."""
    return json.dumps(recorded, indent=1, ensure_ascii=False) + "\n"


def main() -> None:
    """Write the recordings next to ``text2sql.llm.fake``."""
    target = Path(str(files("text2sql.llm").joinpath(RECORDINGS)))
    target.write_text(render(build()), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
