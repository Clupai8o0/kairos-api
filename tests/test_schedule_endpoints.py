import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_schedule_run_stub(client: AsyncClient) -> None:
    response = await client.post("/api/v1/schedule/run")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_schedule_today_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/schedule/today")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_schedule_week_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/schedule/week")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_free_slots_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/schedule/free-slots")
    assert response.status_code == 200
    assert response.json() == []
