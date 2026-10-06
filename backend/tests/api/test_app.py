from httpx import ASGITransport, AsyncClient

from text2sql.api.app import create_app
from text2sql.config.settings import Settings


async def test_healthz(settings: Settings) -> None:
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
