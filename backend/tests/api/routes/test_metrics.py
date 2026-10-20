import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.api.conftest import Fakes
from tests.observability.support import attrs
from text2sql.api.app import create_app
from text2sql.api.services import Services
from text2sql.config.settings import Settings


async def test_metrics_after_a_question(
    client: AsyncClient, auth: dict[str, str], fakes: Fakes
) -> None:
    await client.post("/v1/query", json={"question": "Orders per status?"}, headers=auth)
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 't2s_queries_total{status="answered"} 1.0' in response.text
    assert 't2s_stage_duration_seconds_count{stage="generate"} 1.0' in response.text
    assert "Orders per status" not in response.text
    assert len(fakes.sink.batches) == 1


async def test_metrics_404_when_disabled(settings: Settings, app: FastAPI) -> None:
    del app

    async def factory(app_settings: Settings) -> Services:
        async def nothing() -> None:
            return None

        return Services(
            settings=app_settings,
            answer=None,  # type: ignore[arg-type]  # never called
            store=None,  # type: ignore[arg-type]
            user_limiter=None,  # type: ignore[arg-type]
            token_limiter=None,  # type: ignore[arg-type]
            ping_redis=nothing,
            close=nothing,
        )  # default observer: disabled

    disabled = create_app(settings, services_factory=factory)
    async with (
        disabled.router.lifespan_context(disabled),
        AsyncClient(transport=ASGITransport(app=disabled), base_url="http://test") as http,
    ):
        response = await http.get("/metrics")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_query_is_traced_with_ids_and_logged_with_user(
    client: AsyncClient,
    auth: dict[str, str],
    fakes: Fakes,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capsys.readouterr()
    response = await client.post(
        "/v1/query",
        json={"question": "Orders per status?"},
        headers={**auth, "X-Request-ID": "req-abc"},
    )
    query_id = response.text.split('"query_id": "', 1)[1].split('"', 1)[0]
    (batch,) = fakes.sink.batches
    root = batch[0]
    assert root["traceId"] == query_id.replace("-", "")
    assert attrs(root)["langfuse.trace.metadata.request_id"] == "req-abc"
    assert "96478" not in json.dumps(batch)  # result rows are never traced

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    request_lines = [line for line in lines if line.get("request_id") == "req-abc"]
    assert request_lines
    assert {line["user_id"] for line in request_lines} == {"demo"}
    access = next(line for line in request_lines if line["event"] == "http_request")
    assert access["path"] == "/v1/query"
