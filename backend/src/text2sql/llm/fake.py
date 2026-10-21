"""Fake LLM mode for load tests: recorded answers with realistic delays, no provider calls.

Enabled only by ``LLM_FAKE_MODE`` (never by default, refused in production). It lets a load
test exercise everything else (API, guard rules, cache, retrieval, validator, executor,
Postgres) without spending free-tier quota:

- a structured output with a ``sql`` field (the generator) gets the recorded SQL for the
  question (``fake_recordings.json``, built from the gold set and the few-shot examples), or a
  simple count for unknown questions;
- one with a ``category`` field (the input classifier) gets ``data_question``;
- embeddings are deterministic pseudo-random unit vectors.

Delays: the median latencies measured on the free tiers, with +-25% jitter, times
``LLM_FAKE_DELAY_SCALE``.
"""

import asyncio
import hashlib
import json
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

import sqlglot
from pydantic import BaseModel
from sqlglot import exp

from text2sql.cache.keys import normalize_question
from text2sql.llm.config import LLMConfig
from text2sql.llm.types import LLMResult, Message, ModelRole, Usage, UsageRole

RECORDINGS = "fake_recordings.json"
UNKNOWN_SQL = "SELECT count(*) AS orders FROM shop.orders AS o"
DELAY_S: dict[UsageRole, float] = {"fast": 0.6, "main": 2.5, "local": 2.5, "embedding": 0.15}
_QUESTION = re.compile(r"<question>\s*(.*?)\s*</question>", re.DOTALL)
_jitter = random.Random()  # noqa: S311 - delays, not security


@cache
def recordings() -> dict[str, str]:
    """Normalised question -> recorded SQL."""
    raw = files("text2sql.llm").joinpath(RECORDINGS).read_text(encoding="utf-8")
    data: dict[str, str] = json.loads(raw)
    return data


def question_of(messages: Sequence[Message]) -> str:
    """The user's question, from the ``<question>`` tag of the last user message."""
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    match = _QUESTION.search(user)
    return match.group(1) if match else user


def tables_of(sql: str) -> list[str]:
    """Schema-qualified tables a query reads (CTE names excluded)."""
    tree = sqlglot.parse_one(sql, read="postgres")
    ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
    names = {f"{t.db}.{t.name}" for t in tree.find_all(exp.Table) if t.name not in ctes and t.db}
    return sorted(names)


async def _sleep(role: UsageRole, config: LLMConfig) -> float:
    scale = config.fake_delay_scale or 0.0
    seconds = DELAY_S[role] * scale * _jitter.uniform(0.75, 1.25)
    if seconds > 0:
        await asyncio.sleep(seconds)
    return round(seconds * 1000, 1)


def _usage(role: UsageRole, model: str, prompt: str, latency_ms: float) -> Usage:
    tokens = max(1, len(prompt) // 4)
    return Usage(
        role=role,
        model=model,
        prompt_tokens=tokens,
        completion_tokens=0 if role == "embedding" else 60,
        total_tokens=tokens + (0 if role == "embedding" else 60),
        latency_ms=latency_ms,
        cost_usd=0.0,
        attempts=1,
        provider="fake",
    )


def _payload(response_model: type[BaseModel], question: str) -> dict[str, object]:
    fields = response_model.model_fields
    if "sql" in fields:
        sql = recordings().get(normalize_question(question), UNKNOWN_SQL)
        return {
            "sql": sql,
            "tables_used": tables_of(sql),
            "explanation": "Recorded answer (fake LLM mode).",
            "assumptions": [],
            "confidence": 0.9,
            "answerable": True,
        }
    if "category" in fields:
        return {"category": "data_question", "reason": "Fake LLM mode."}
    msg = f"fake LLM mode has no recording for {response_model.__name__}"
    raise TypeError(msg)


async def fake_structured[T: BaseModel](
    messages: Sequence[Message], response_model: type[T], role: ModelRole, config: LLMConfig
) -> LLMResult[T]:
    """What ``generate_structured`` returns in fake mode."""
    latency = await _sleep(role, config)
    prompt = "".join(m["content"] for m in messages)
    output = response_model.model_validate(_payload(response_model, question_of(messages)))
    return LLMResult(output, _usage(role, config.models[role], prompt, latency))


@dataclass(frozen=True, slots=True)
class FakeEmbedding:
    """Same shape as ``EmbeddingResult``."""

    vectors: list[list[float]]
    usage: Usage


def fake_vector(text: str, dimensions: int) -> list[float]:
    """A deterministic unit vector for ``text``."""
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    rng = random.Random(seed)  # noqa: S311 - not security
    values = [rng.gauss(0.0, 1.0) for _ in range(dimensions)]
    norm = sum(v * v for v in values) ** 0.5
    return [v / norm for v in values]


async def fake_embeddings(texts: Sequence[str], config: LLMConfig) -> FakeEmbedding:
    """What ``embed_texts`` returns in fake mode."""
    latency = await _sleep("embedding", config) if texts else 0.0
    dimensions = config.embedding_dimensions or 1536
    usage = _usage("embedding", config.embedding_model, "".join(texts), latency)
    return FakeEmbedding([fake_vector(t, dimensions) for t in texts], usage)
