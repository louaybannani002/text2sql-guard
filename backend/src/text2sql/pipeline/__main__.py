"""``python -m text2sql.pipeline "question"``: print the validated SQL (``make ask Q="..."``).

The SQL goes to stdout, so it can be piped; a short header of SQL comments explains it.
Nothing is executed.
"""

import argparse
import asyncio
import sys
from typing import TextIO

from text2sql.config.settings import Settings, get_settings
from text2sql.db.connection import create_pool
from text2sql.guard.sql_policy import load_policy
from text2sql.guard.sql_validator import Rejection
from text2sql.llm import LLMConfig, LLMError
from text2sql.observability.logging import configure_logging
from text2sql.pipeline.ask import AskDependencies, AskResult, ask
from text2sql.retrieval.retriever import CatalogNotBuiltError

EXIT_FAILED = 1
EXIT_UNANSWERABLE = 2
EXIT_BLOCKED = 3
EXIT_REJECTED = 4


def _commented(sql: str) -> list[str]:
    return [f"--   {line}" for line in sql.strip().splitlines()]


def format_result(result: AskResult) -> str:
    """The validated SQL with an explanatory comment header (or why there is no SQL)."""
    draft, context, validation = result.draft, result.context, result.validation
    cost = "unknown" if result.cost_usd is None else f"${result.cost_usd:.4f}"
    if draft is None or context is None:
        verdict = result.verdict
        lines = [f"-- BLOCKED ({verdict.category}): {verdict.reason}", f"-- cost: {cost}"]
        return "\n".join(lines) + "\n"
    header = [
        f"-- {draft.explanation}",
        *(f"-- assumption: {a}" for a in draft.assumptions),
        (
            f"-- confidence: {draft.confidence:.2f} | schema context: "
            f"{', '.join(context.relations)} ({context.tokens} tokens) | cost: {cost}"
        ),
    ]
    if validation is None:
        return "\n".join(["-- NOT ANSWERABLE from the available data.", *header]) + "\n"
    if isinstance(validation, Rejection):
        lines = [
            f"-- REJECTED by the SQL validator ({validation.rule}): {validation.reason}",
            *header,
            "-- draft (not runnable):",
            *_commented(draft.sql),
        ]
        return "\n".join(lines) + "\n"
    rewrites = [f"-- validator: {r}" for r in validation.rewrites]
    return "\n".join([*header, *rewrites, validation.sql + ";"]) + "\n"


def exit_code(result: AskResult) -> int:
    """0 (SQL), 2 (not answerable), 3 (blocked by the input guard), 4 (rejected SQL)."""
    if result.draft is None:
        return EXIT_BLOCKED
    if result.validation is None:
        return EXIT_UNANSWERABLE
    return EXIT_REJECTED if isinstance(result.validation, Rejection) else 0


async def run(question: str, settings: Settings, out: TextIO, err: TextIO) -> int:
    """Answer one question; returns the process exit code."""
    pool = await create_pool(settings.app_database_url, max_size=3)
    try:
        async with pool.acquire() as conn:
            policy = await load_policy(conn)
        deps = AskDependencies(
            db=pool,
            llm=LLMConfig.from_settings(settings),
            policy=policy,
            token_budget=settings.retrieval_token_budget,
        )
        result = await ask(question, deps)
    except (CatalogNotBuiltError, LLMError) as exc:
        err.write(f"error: {exc}\n")
        return EXIT_FAILED
    finally:
        await pool.close()
    out.write(format_result(result))
    return exit_code(result)


def main() -> None:
    """Exit 0 (SQL), 1 (error), 2 (not answerable), 3 (blocked) or 4 (SQL rejected)."""
    parser = argparse.ArgumentParser(prog="python -m text2sql.pipeline")
    parser.add_argument("question", help="business question in plain language")
    parser.add_argument("--verbose", action="store_true", help="show structured logs")
    args = parser.parse_args()
    if not args.question.strip():
        parser.error("the question is empty")

    settings = get_settings()
    # Logs share stdout with the SQL, so keep them quiet unless asked.
    configure_logging("INFO" if args.verbose else "ERROR", json=settings.app_env != "development")
    sys.exit(asyncio.run(run(args.question, settings, sys.stdout, sys.stderr)))


if __name__ == "__main__":
    main()
