import uuid

import pytest
from httpx import AsyncClient

from tests.api.conftest import Fakes, make_answer, parse_sse
from text2sql.pipeline.answer import Answer
from text2sql.pipeline.events import EventSink, StageError


async def _ask(
    client: AsyncClient, auth: dict[str, str], question: str = "Orders per status?"
) -> str:
    response = await client.post("/v1/query", json={"question": question}, headers=auth)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    return response.text


async def test_streams_stage_events_then_the_answer(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    events = parse_sse(await _ask(client, auth))
    names = [name for name, _ in events]
    assert names[0] == "query"
    assert names[1:-1] == ["stage_started", "stage_done"] * 5
    assert names[-1] == "answer"
    assert [data["stage"] for name, data in events if name == "stage_done"] == [
        "input_guard",
        "retrieve",
        "generate",
        "validate",
        "execute",
    ]


async def test_final_event_has_the_answer_and_nothing_internal(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    text = await _ask(client, auth)
    query_id = parse_sse(text)[0][1]["query_id"]
    answer = parse_sse(text)[-1][1]

    assert answer["query_id"] == query_id
    assert answer["status"] == "answered"
    assert answer["sql"].startswith("SELECT o.order_status")
    assert answer["explanation"] == "Counts orders by status."
    assert answer["assumptions"] == ["All statuses count."]
    assert answer["columns"] == [
        {"name": "order_status", "type": "text"},
        {"name": "n", "type": "int8"},
    ]
    assert answer["rows"] == [["delivered", 96478]]
    assert (answer["row_count"], answer["truncated"], answer["attempts"]) == (1, False, 1)
    assert answer["timings"]["total_ms"] == 2500.0
    assert answer["timings"]["stages"][0] == {
        "stage": "generate",
        "attempt": 1,
        "status": "ok",
        "latency_ms": 2000.0,
    }
    assert (answer["tokens"], answer["cost_usd"]) == (3000, 0.006)
    # Answer.detail and the trace's inputs/outputs are internal.
    assert "INTERNAL" not in text
    assert "internal_trace_detail" not in text


async def test_query_is_recorded_for_the_user(
    client: AsyncClient, auth: dict[str, str], fakes: Fakes
) -> None:
    query_id = uuid.UUID(parse_sse(await _ask(client, auth, "Orders?"))[0][1]["query_id"])
    assert fakes.store.queries[query_id] == {
        "user_id": "demo",
        "question": "Orders?",
        "status": "answered",
    }


@pytest.mark.parametrize("status", ["blocked", "rejected", "failed", "cannot_answer"])
async def test_sql_is_only_sent_for_answered_questions(
    client: AsyncClient, auth: dict[str, str], fakes: Fakes, status: str
) -> None:
    async def refusing(question: str, sink: EventSink) -> Answer:
        del sink
        return make_answer(question, status=status, result=None, message="No.")

    fakes.answer = refusing
    answer = parse_sse(await _ask(client, auth))[-1][1]
    assert (answer["status"], answer["message"], answer["sql"]) == (status, "No.", None)
    assert answer["rows"] == []


async def test_stage_errors_are_streamed(
    client: AsyncClient, auth: dict[str, str], fakes: Fakes
) -> None:
    async def failing_validation(question: str, sink: EventSink) -> Answer:
        await sink(
            StageError(
                stage="validate",
                attempt=1,
                latency_ms=3.0,
                error="rejected:columns",
                message="Unknown column shop.orders.status.",
                retryable=True,
            )
        )
        return make_answer(question)

    fakes.answer = failing_validation
    events = parse_sse(await _ask(client, auth))
    assert events[1] == (
        "error",
        {
            "type": "error",
            "stage": "validate",
            "attempt": 1,
            "latency_ms": 3.0,
            "error": "rejected:columns",
            "message": "Unknown column shop.orders.status.",
            "retryable": True,
        },
    )


async def test_unexpected_crash_becomes_a_generic_server_error_event(
    client: AsyncClient, auth: dict[str, str], fakes: Fakes
) -> None:
    async def crashing(question: str, sink: EventSink) -> Answer:
        del question, sink
        msg = "asyncpg: relation app.secret_table does not exist at line 3"
        raise RuntimeError(msg)

    fakes.answer = crashing
    text = await _ask(client, auth)
    name, data = parse_sse(text)[-1]
    assert name == "server_error"
    assert data["error"]["code"] == "internal_error"
    assert data["error"]["request_id"]
    assert "secret_table" not in text
    (recorded,) = fakes.store.queries.values()
    assert recorded["status"] == "error"


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/v1/query", json={"question": "x"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    "body", [{}, {"question": ""}, {"question": "x" * 2001}, {"question": 42}, {"q": "x"}]
)
async def test_invalid_bodies_get_the_uniform_error(
    client: AsyncClient, auth: dict[str, str], body: dict[str, object]
) -> None:
    response = await client.post("/v1/query", json=body, headers=auth)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert "question" in error["message"]
    assert "x" * 50 not in response.text  # the input is never echoed back


async def test_per_user_rate_limit(client: AsyncClient, auth: dict[str, str]) -> None:
    for _ in range(20):
        assert (
            await client.post("/v1/query", json={"question": "q"}, headers=auth)
        ).status_code == 200
    blocked = await client.post("/v1/query", json={"question": "q"}, headers=auth)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) > 0
    assert blocked.headers["x-ratelimit-remaining"] == "0"
