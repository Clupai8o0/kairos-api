import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_openapi_docs(client: AsyncClient) -> None:
    response = await client.get("/docs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_openapi_schema_contains_core_routes(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200

    paths = response.json()["paths"]
    assert "/api/v1/tasks/" in paths
    assert "/api/v1/projects/" in paths
    assert "/api/v1/tags/" in paths
    assert "/api/v1/views/" in paths
    assert "/api/v1/schedule/run" in paths
    assert "/api/v1/blackout-days/" in paths
    assert "/api/v1/auth/google/login" in paths


@pytest.mark.asyncio
async def test_tasks_endpoint_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/")
    assert response.status_code == 401
