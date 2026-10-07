"""``python -m text2sql.pipeline "question"``: print the drafted SQL (``make ask Q="..."``).

The SQL goes to stdout, so it can be piped; a short header of SQL comments explains it.
Nothing is executed.
"""

import argparse
import asyncio
import sys
from typing import TextIO

from text2sql.config.settings import Settings, get_settings
from text2sql.db.connection import create_pool
from text2sql.llm import LLMConfig, LLMError
from text2sql.observability.logging import configure_logging
from text2sql.pipeline.ask import AskResult, ask
from text2sql.retrieval.retriever import CatalogNotBuiltError

EXIT_UNANSWERABLE = 2
EXIT_FAILED = 1


def format_result(result: AskResult) -> str:
    """The SQL with an explanatory comment header (or the reason it is not answerable)."""
    draft = result.draft
    cost = "unknown" if result.cost_usd is None else f"${result.cost_usd:.4f}"
    header = [
        f"-- {draft.explanation}",
        *(f"-- assumption: {a}" for a in draft.assumptions),
        (
            f"-- confidence: {draft.confidence:.2f} | schema context: "
            f"{', '.join(result.context.relations)} ({result.context.tokens} tokens) | cost: {cost}"
        ),
    ]
    if not draft.answerable:
        return "\n".join(["-- NOT ANSWERABLE from the available data.", *header]) + "\n"
    return "\n".join([*header, draft.sql.strip() + ";"]) + "\n"


async def run(question: str, settings: Settings, out: TextIO, err: TextIO) -> int:
    """Answer one question; returns the process exit code."""
    pool = await create_pool(settings.app_database_url, max_size=3)
    try:
        result = await ask(
            question,
            db=pool,
            llm=LLMConfig.from_settings(settings),
            token_budget=settings.retrieval_token_budget,
        )
    except (CatalogNotBuiltError, LLMError) as exc:
        err.write(f"error: {exc}\n")
        return EXIT_FAILED
    finally:
        await pool.close()
    out.write(format_result(result))
    return 0 if result.draft.answerable else EXIT_UNANSWERABLE


def main() -> None:
    """Parse arguments, answer, exit with 0 (SQL), 2 (not answerable) or 1 (error)."""
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
