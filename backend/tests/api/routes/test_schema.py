from httpx import AsyncClient


async def test_schema_summary(client: AsyncClient, auth: dict[str, str]) -> None:
    response = await client.get("/v1/schema", headers=auth)
    assert response.status_code == 200
    assert response.json() == {
        "tables": [
            {
                "name": "shop.orders",
                "kind": "table",
                "description": "One row per order.",
                "columns": [
                    {"name": "order_status", "type": "text", "description": "Lifecycle state."}
                ],
            }
        ]
    }


async def test_schema_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/v1/schema")).status_code == 401
