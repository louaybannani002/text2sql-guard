from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.api.conftest import Fakes
from text2sql.api.app import create_app
from text2sql.config.settings import Settings


async def test_lifespan_creates_and_closes_services(app: FastAPI, fakes: Fakes) -> None:
    async with app.router.lifespan_context(app):
        assert app.state.services.store is fakes.store
        assert not fakes.closed
    assert fakes.closed


async def test_docs_are_disabled_in_production(settings: Settings) -> None:
    async def never_called(_settings: Settings) -> object:
        raise AssertionError

    for env, status in (("test", 200), ("production", 404)):
        app = create_app(settings.model_copy(update={"app_env": env}), never_called)  # type: ignore[arg-type]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            assert (await http.get("/docs")).status_code == status


async def test_every_route_is_documented(app: FastAPI) -> None:
    assert {
        "/healthz",
        "/readyz",
        "/v1/auth/token",
        "/v1/query",
        "/v1/schema",
        "/v1/feedback",
    } == set(app.openapi()["paths"])
