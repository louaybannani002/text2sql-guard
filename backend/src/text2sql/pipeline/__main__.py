"""``python -m text2sql.pipeline "question"`` (``make ask Q="..."``): answer one question.

Runs the whole pipeline, including execution as ``t2s_reader``, and prints the SQL, a result
preview and a one-line trace. Exit codes: 0 answered, 1 failed, 2 cannot answer,
3 blocked by the input guard, 4 rejected by a security check.
"""

import argparse
import asyncio
import sys
from typing import TextIO

from text2sql.config.settings import Settings, get_settings
from text2sql.db.connection import create_pool
from text2sql.executor.executor import QueryExecutor
from text2sql.guard.sql_policy import load_policy
from text2sql.llm import LLMConfig
from text2sql.llm.embeddings import embed_texts
from text2sql.observability.logging import configure_logging
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.orchestrator import OrchestratorDeps, answer

EXIT_CODES = {"answered": 0, "failed": 1, "cannot_answer": 2, "blocked": 3, "rejected": 4}
PREVIEW_ROWS = 20


def _cell(value: object) -> str:
    text = "NULL" if value is None else str(value)
    return text if len(text) <= 40 else text[:39] + "…"  # noqa: PLR2004


def format_answer(result: Answer) -> str:
    """Human-readable answer: message, SQL, result preview and trace summary."""
    lines = [f"[{result.status}] {result.message}"]
    lines += [f"assumption: {a}" for a in result.assumptions]
    if result.sql and result.status in {"answered", "failed"}:
        lines += ["", result.sql.strip() + ";"]
    if result.result is not None:
        data = result.result
        lines += ["", " | ".join(c.name for c in data.columns)]
        lines += [" | ".join(_cell(v) for v in row) for row in data.rows[:PREVIEW_ROWS]]
        shown = min(PREVIEW_ROWS, data.row_count)
        more = " (more rows exist; result capped)" if data.truncated else ""
        lines.append(f"({shown} of {data.row_count} rows shown{more})")
    trace = result.trace
    stages = ", ".join(f"{s.stage}#{s.attempt} {s.latency_ms:.0f}ms" for s in trace.stages)
    cost = "unknown" if trace.total_cost_usd is None else f"${trace.total_cost_usd:.4f}"
    summary = f"{trace.total_ms:.0f} ms | {trace.total_tokens} tokens | cost {cost}"
    lines += ["", f"-- attempts: {result.attempts} | {summary}", f"-- stages: {stages}"]
    return "\n".join(lines) + "\n"


async def run(question: str, settings: Settings, out: TextIO) -> int:
    """Answer one question; returns the process exit code."""
    llm = LLMConfig.from_settings(settings)
    catalog = await create_pool(settings.app_database_url, max_size=3)
    executor = await QueryExecutor.create(settings)
    try:
        async with catalog.acquire() as conn:
            policy = await load_policy(conn)
        deps = OrchestratorDeps(
            db=catalog,
            llm=llm,
            embed=lambda texts: embed_texts(texts, config=llm),
            policy=policy,
            executor=executor,
            token_budget=settings.retrieval_token_budget,
        )
        result = await answer(question, deps)
    finally:
        await executor.close()
        await catalog.close()
    out.write(format_answer(result))
    return EXIT_CODES[result.status]


def main() -> None:
    """Parse arguments, answer, exit with the status code (see module docstring)."""
    parser = argparse.ArgumentParser(prog="python -m text2sql.pipeline")
    parser.add_argument("question", help="business question in plain language")
    parser.add_argument("--verbose", action="store_true", help="show structured logs")
    args = parser.parse_args()
    if not args.question.strip():
        parser.error("the question is empty")

    settings = get_settings()
    # Logs share stdout with the answer, so keep them quiet unless asked.
    configure_logging("INFO" if args.verbose else "ERROR", json=settings.app_env != "development")
    sys.exit(asyncio.run(run(args.question, settings, sys.stdout)))


if __name__ == "__main__":
    main()
