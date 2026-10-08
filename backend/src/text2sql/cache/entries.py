"""What the caches store: validated SQL with its explanation, and (exact cache only) rows."""

from pydantic import BaseModel, ConfigDict

from text2sql.executor.executor import QueryResult


class CachedSql(BaseModel):
    """A query that passed the validator, with the text the user saw alongside it.

    It is validated again before every reuse: the policy may have changed since.
    """

    model_config = ConfigDict(frozen=True)

    sql: str
    explanation: str
    assumptions: list[str]


class CachedAnswer(CachedSql):
    """An exact-cache entry: the query and the result it produced."""

    result: QueryResult
