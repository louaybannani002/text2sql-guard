"""What the orchestrator depends on, built once at application startup."""

from dataclasses import dataclass
from typing import Protocol

from text2sql.executor.executor import QueryResult
from text2sql.guard.sql_policy import SqlPolicy
from text2sql.guard.sql_validator import ValidatedSql
from text2sql.llm import LLMConfig
from text2sql.retrieval.embedding import Embedder
from text2sql.retrieval.retriever import ConnectionSource


class Executor(Protocol):
    """Runs validated SQL (``QueryExecutor`` in production)."""

    async def execute(self, validated: ValidatedSql) -> QueryResult:
        """Execute and return rows, or raise ``ExecutionError``."""
        ...


@dataclass(frozen=True, slots=True)
class OrchestratorDeps:
    """Everything ``answer`` needs, built once at startup."""

    db: ConnectionSource  # catalog (t2s_app)
    llm: LLMConfig
    embed: Embedder
    policy: SqlPolicy
    executor: Executor  # t2s_reader
    token_budget: int
    max_retries: int = 2
    k: int = 5
