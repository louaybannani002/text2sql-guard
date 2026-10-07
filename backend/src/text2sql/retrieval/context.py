"""What retrieval hands to SQL generation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from text2sql.llm.types import Usage


class FewShotExample(BaseModel):
    """A solved question shown to the model as a style reference."""

    model_config = ConfigDict(frozen=True)

    question: str
    sql: str


class RetrievedExample(FewShotExample):
    """A few-shot example found by similarity to the user's question."""

    example_id: str
    similarity: float = Field(description="Cosine similarity of the questions, -1 to 1.")


class RetrievedTable(BaseModel):
    """One relation in the context, and why it is there."""

    model_config = ConfigDict(frozen=True)

    relation: str
    reason: Literal["retrieved", "join_path"]
    score: float = Field(description="Reciprocal Rank Fusion score; 0 for join-path tables.")
    vector_rank: int | None = None
    text_rank: int | None = None
    detail: Literal["full", "no_examples", "columns_only", "dropped"] = "full"


class SchemaContext(BaseModel):
    """Relations (rendered as DDL-like text within a token budget) and few-shot examples."""

    model_config = ConfigDict(frozen=True)

    question: str
    tables: list[RetrievedTable] = Field(description="Relevance order; includes dropped ones.")
    examples: list[RetrievedExample]
    text: str = Field(description="Schema context for the prompt, within token_budget.")
    tokens: int
    token_budget: int
    usage: Usage = Field(description="Embedding of the question.")

    @property
    def relations(self) -> list[str]:
        """Relations actually present in ``text``."""
        return [t.relation for t in self.tables if t.detail != "dropped"]
