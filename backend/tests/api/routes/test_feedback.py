import uuid

import pytest
from httpx import AsyncClient

from tests.api.conftest import Fakes, parse_sse


async def _query_id(client: AsyncClient, auth: dict[str, str]) -> str:
    response = await client.post("/v1/query", json={"question": "q"}, headers=auth)
    query_id: str = parse_sse(response.text)[0][1]["query_id"]
    return query_id


async def test_feedback_is_stored(client: AsyncClient, auth: dict[str, str], fakes: Fakes) -> None:
    query_id = await _query_id(client, auth)
    response = await client.post(
        "/v1/feedback",
        json={"query_id": query_id, "rating": 4, "comment": "  Useful, thanks.  "},
        headers=auth,
    )
    assert response.status_code == 201
    assert response.json() == {"feedback_id": 1}
    assert fakes.store.feedback[(uuid.UUID(query_id), "demo")] == {
        "rating": 4,
        "comment": "Useful, thanks.",
    }


async def test_unknown_or_foreign_queries_look_the_same(
    client: AsyncClient, auth: dict[str, str], fakes: Fakes
) -> None:
    foreign = uuid.uuid4()
    fakes.store.queries[foreign] = {
        "user_id": "someone-else",
        "question": "q",
        "status": "answered",
    }
    for query_id in (str(uuid.uuid4()), str(foreign)):
        response = await client.post(
            "/v1/feedback", json={"query_id": query_id, "rating": 5}, headers=auth
        )
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "No such query."


@pytest.mark.parametrize(
    "body",
    [
        {"query_id": "not-a-uuid", "rating": 3},
        {"query_id": str(uuid.uuid4()), "rating": 0},
        {"query_id": str(uuid.uuid4()), "rating": 6},
        {"query_id": str(uuid.uuid4()), "rating": 3, "comment": "x" * 2001},
    ],
    ids=["bad_uuid", "rating_low", "rating_high", "long_comment"],
)
async def test_invalid_feedback(
    client: AsyncClient, auth: dict[str, str], body: dict[str, object]
) -> None:
    response = await client.post("/v1/feedback", json=body, headers=auth)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
