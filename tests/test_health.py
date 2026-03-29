import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_openapi_docs(client: AsyncClient) -> None:
    response = await client.get("/docs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_tasks_endpoint_stub(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/")
    assert response.status_code == 200
    assert response.json() == []
