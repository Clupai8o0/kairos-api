import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_views_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/views/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_view_stub(client: AsyncClient) -> None:
    response = await client.post("/api/v1/views/")
    assert response.status_code == 201
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_get_view_stub(client: AsyncClient) -> None:
    response = await client.get("/api/v1/views/view_123")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_get_view_tasks_stub(client: AsyncClient) -> None:
    response = await client.get("/api/v1/views/view_123/tasks")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_update_view_stub(client: AsyncClient) -> None:
    response = await client.patch("/api/v1/views/view_123")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_delete_view_stub(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/views/view_123")
    assert response.status_code == 204
    assert response.text == ""
