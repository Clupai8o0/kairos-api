import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_projects_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_project_stub(client: AsyncClient) -> None:
    response = await client.post("/api/v1/projects/")
    assert response.status_code == 201
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_get_project_stub(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects/project_123")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_update_project_stub(client: AsyncClient) -> None:
    response = await client.patch("/api/v1/projects/project_123")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_delete_project_stub(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/projects/project_123")
    assert response.status_code == 204
    assert response.text == ""
