import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_tasks_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_task_stub(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tasks/")
    assert response.status_code == 201
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_get_task_stub(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/task_123")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_update_task_stub(client: AsyncClient) -> None:
    response = await client.patch("/api/v1/tasks/task_123")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_delete_task_stub(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/tasks/task_123")
    assert response.status_code == 204
    assert response.text == ""
