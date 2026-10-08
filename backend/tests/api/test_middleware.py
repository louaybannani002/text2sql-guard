from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient


async def test_request_id_is_generated(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert len(response.headers["x-request-id"]) == 32


async def test_valid_incoming_request_id_is_kept(client: AsyncClient) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": "trace-abc_123.4"})
    assert response.headers["x-request-id"] == "trace-abc_123.4"


@pytest.mark.parametrize("bad", ["has spaces", "x" * 65, "<script>", "a\tb"])
async def test_unsafe_incoming_request_id_is_replaced(client: AsyncClient, bad: str) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": bad})
    assert response.headers["x-request-id"] != bad
    assert len(response.headers["x-request-id"]) == 32


async def test_errors_carry_the_request_id(client: AsyncClient) -> None:
    response = await client.get("/v1/schema", headers={"X-Request-ID": "req-42"})
    assert response.json()["error"]["request_id"] == "req-42"


async def test_body_over_the_limit_by_content_length(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    payload = '{"question": "' + "x" * 20_000 + '"}'
    response = await client.post(
        "/v1/query", content=payload, headers=auth | {"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.headers["x-request-id"]


async def test_body_over_the_limit_without_content_length(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    async def chunks() -> AsyncIterator[bytes]:  # streamed: no Content-Length header
        yield b'{"question": "'
        for _ in range(40):
            yield b"x" * 1000
        yield b'"}'

    response = await client.post(
        "/v1/query", content=chunks(), headers=auth | {"Content-Type": "application/json"}
    )
    assert response.status_code == 413


async def test_cors_allows_only_listed_origins(client: AsyncClient) -> None:
    preflight = {"Access-Control-Request-Method": "POST"}
    allowed = await client.options(
        "/v1/query", headers=preflight | {"Origin": "http://localhost:5173"}
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in allowed.headers

    other = await client.options(
        "/v1/query", headers=preflight | {"Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in other.headers
