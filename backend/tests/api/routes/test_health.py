from httpx import AsyncClient

from tests.api.conftest import Fakes


async def test_healthz_needs_nothing(client: AsyncClient, fakes: Fakes) -> None:
    fakes.store.up = fakes.redis.up = False  # liveness must not depend on dependencies
    response = await client.get("/healthz")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


async def test_readyz_ok(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_readyz_reports_each_dependency_without_details(
    client: AsyncClient, fakes: Fakes
) -> None:
    fakes.redis.up = False
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "ok", "redis": "unavailable"},
    }
    assert "redis down" not in response.text
