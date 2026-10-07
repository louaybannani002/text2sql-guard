"""Retrieval quality eval: recall@k on 15 labelled questions, with real embeddings.

Runs only with `make test-integration` and an OPENAI_API_KEY. The catalog is rebuilt with the
real embedding model inside the test's rolled-back transaction (~3,900 tokens, < $0.0001).
"""

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import pytest
from pydantic import ValidationError

from tests.support.connection_source import SingleConnectionSource
from text2sql.config.settings import Settings
from text2sql.llm import LLMConfig
from text2sql.llm.embeddings import EmbeddingResult, embed_texts
from text2sql.retrieval.build import build_catalog
from text2sql.retrieval.examples import load_examples
from text2sql.retrieval.retriever import retrieve

BACKEND = Path(__file__).parents[2]
QUESTIONS = tomllib.loads(
    (BACKEND.parent / "eval" / "retrieval" / "questions.toml").read_text(encoding="utf-8")
)["question"]
TARGET_RECALL = 0.95


def _live_settings() -> Settings | None:
    try:
        settings = Settings()  # environment, then backend/.env
    except ValidationError:
        return None
    return settings if settings.openai_api_key.get_secret_value() else None


LIVE = _live_settings()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(LIVE is None, reason="OPENAI_API_KEY is not set"),
]


@dataclass(frozen=True)
class _Row:
    question: str
    expected: frozenset[str]
    retrieved: dict[int, frozenset[str]]  # k -> relations in the context

    def recall(self, k: int) -> float:
        return len(self.expected & self.retrieved[k]) / len(self.expected)


class _MemoEmbedder:
    """Embeds each distinct question once, so evaluating several k costs one call."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.cache: dict[tuple[str, ...], EmbeddingResult] = {}

    async def __call__(self, texts: Sequence[str]) -> EmbeddingResult:
        key = tuple(texts)
        if key not in self.cache:
            self.cache[key] = await embed_texts(texts, config=self.config)
        return self.cache[key]


def _report(rows: list[_Row], ks: Sequence[int]) -> str:
    lines = ["", f"retrieval recall on {len(rows)} questions"]
    for row in rows:
        misses = sorted(row.expected - row.retrieved[max(ks)])
        scores = "  ".join(f"@{k}={row.recall(k):.2f}" for k in ks)
        lines.append(f"  {scores}  {row.question}" + (f"  MISSING {misses}" if misses else ""))
    lines += [f"  recall@{k} = {sum(r.recall(k) for r in rows) / len(rows):.3f}" for k in ks]
    return "\n".join(lines)


async def test_recall_at_5(admin: asyncpg.Connection, capsys: pytest.CaptureFixture[str]) -> None:
    assert LIVE is not None
    llm = LLMConfig.from_settings(LIVE)
    embed = _MemoEmbedder(llm)
    await build_catalog(
        admin,
        examples=load_examples(BACKEND / LIVE.examples_seed_path),
        embed=lambda texts: embed_texts(texts, config=llm),
        embedding_model=llm.embedding_model,
        force=True,
    )
    await admin.execute("SET LOCAL ROLE t2s_app")  # retrieve with the app's privileges
    source = SingleConnectionSource(admin)

    ks = (3, 5)
    rows = []
    for item in QUESTIONS:
        retrieved = {}
        for k in ks:
            context = await retrieve(
                item["text"], k, db=source, embed=embed, token_budget=LIVE.retrieval_token_budget
            )
            retrieved[k] = frozenset(context.relations)
        rows.append(_Row(item["text"], frozenset(item["expected"]), retrieved))

    with capsys.disabled():
        print(_report(rows, ks))  # noqa: T201 - the eval report is this test's output
    recall = sum(r.recall(5) for r in rows) / len(rows)
    assert recall >= TARGET_RECALL, _report(rows, ks)
