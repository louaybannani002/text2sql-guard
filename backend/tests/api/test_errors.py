from fastapi import FastAPI
from httpx import AsyncClient

from text2sql.api.errors import ApiError


async def test_unknown_route(client: AsyncClient) -> None:
    response = await client.get("/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_wrong_method(client: AsyncClient) -> None:
    response = await client.get("/v1/query")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_unexpected_exception_reveals_nothing(app: FastAPI, client: AsyncClient) -> None:
    @app.get("/boom")
    async def boom() -> None:
        msg = 'column "customer_city" permission denied; SELECT secret FROM shop.customers'
        raise RuntimeError(msg)

    response = await client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Something went wrong. Please try again.",
            "request_id": response.headers["x-request-id"],
        }
    }
    assert "customer_city" not in response.text
    assert "Traceback" not in response.text


async def test_api_error_shape(app: FastAPI, client: AsyncClient) -> None:
    @app.get("/teapot")
    async def teapot() -> None:
        raise ApiError(418, "teapot", "Short and stout.", headers={"X-Extra": "1"})

    response = await client.get("/teapot")
    assert response.status_code == 418
    assert response.json()["error"]["code"] == "teapot"
    assert response.headers["x-extra"] == "1"


async def test_malformed_json_names_the_body(client: AsyncClient, auth: dict[str, str]) -> None:
    response = await client.post(
        "/v1/query", content="{", headers=auth | {"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Invalid request: check body."
