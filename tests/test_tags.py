import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_tags_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tags/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_tag_stub(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tags/")
    assert response.status_code == 201
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_update_tag_stub(client: AsyncClient) -> None:
    response = await client.patch("/api/v1/tags/tag_123")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_delete_tag_stub(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/tags/tag_123")
    assert response.status_code == 204
    assert response.text == ""
