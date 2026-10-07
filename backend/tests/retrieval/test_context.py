from text2sql.llm.types import Usage
from text2sql.retrieval.context import (
    FewShotExample,
    RetrievedExample,
    RetrievedTable,
    SchemaContext,
)

USAGE = Usage(
    role="embedding",
    model="m",
    prompt_tokens=1,
    completion_tokens=0,
    total_tokens=1,
    latency_ms=0.0,
    cost_usd=0.0,
    attempts=1,
)


def test_relations_excludes_dropped_tables() -> None:
    context = SchemaContext(
        question="q",
        tables=[
            RetrievedTable(relation="shop.orders", reason="retrieved", score=0.03),
            RetrievedTable(relation="shop.customers", reason="join_path", score=0.0),
            RetrievedTable(
                relation="shop.sellers", reason="retrieved", score=0.01, detail="dropped"
            ),
        ],
        examples=[],
        text="CREATE TABLE shop.orders ();",
        tokens=5,
        token_budget=10,
        usage=USAGE,
    )
    assert context.relations == ["shop.orders", "shop.customers"]


def test_retrieved_example_is_a_few_shot_example() -> None:
    example = RetrievedExample(example_id="a", question="q", sql="SELECT 1", similarity=0.9)
    assert isinstance(example, FewShotExample)
