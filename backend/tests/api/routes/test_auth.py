import pytest
from httpx import AsyncClient

from text2sql.api.auth import issue_token
from text2sql.config.settings import Settings


async def test_token_for_the_demo_user(client: AsyncClient, settings: Settings) -> None:
    response = await client.post(
        "/v1/auth/token",
        json={"username": "demo", "password": settings.demo_password.get_secret_value()},
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["token_type"], body["expires_in"]) == ("bearer", 900)
    assert body["access_token"].count(".") == 2


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": "demo", "password": "wrong"},
        {"username": "admin", "password": "demo-password-for-tests"},
    ],
)
async def test_wrong_credentials_get_one_generic_answer(
    client: AsyncClient, credentials: dict[str, str]
) -> None:
    response = await client.post("/v1/auth/token", json=credentials)
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "unauthorized",
        "message": "Invalid username or password.",
        "request_id": response.headers["x-request-id"],
    }


async def test_login_attempts_are_rate_limited(client: AsyncClient) -> None:
    for _ in range(10):
        await client.post("/v1/auth/token", json={"username": "demo", "password": "guess"})
    blocked = await client.post("/v1/auth/token", json={"username": "demo", "password": "guess"})
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Bearer not.a.jwt", "Basic ZGVtbzpwdw==", "bearer   "],
)
async def test_bad_authorization_headers(client: AsyncClient, header: str) -> None:
    headers = {"Authorization": header} if header else {}
    response = await client.get("/v1/schema", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_expired_token(client: AsyncClient, settings: Settings) -> None:
    old = issue_token("demo", settings.jwt_secret, 60, now=0)
    response = await client.get(
        "/v1/schema", headers={"Authorization": f"Bearer {old.access_token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid or expired token."
