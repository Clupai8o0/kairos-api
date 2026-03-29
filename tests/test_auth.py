import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_google_oauth_login_stub(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/google/login")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}


@pytest.mark.asyncio
async def test_google_oauth_callback_stub(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/google/callback")
    assert response.status_code == 200
    assert response.json() == {"detail": "Not implemented"}
