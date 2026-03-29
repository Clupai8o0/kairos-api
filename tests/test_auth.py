"""Auth tests per references/testing.md spec."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from kairos.services.auth_service import create_access_token


# ── Google OAuth ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_google_oauth_redirect(unauthed_client: AsyncClient) -> None:
    """GET /auth/google/login returns 302 redirect to Google."""
    with patch("kairos.api.auth._build_flow") as mock_flow_factory:
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?client_id=test",
            "state123",
        )
        mock_flow_factory.return_value = mock_flow

        response = await unauthed_client.get("/auth/google/login", follow_redirects=False)
        assert response.status_code == 302
        assert "accounts.google.com" in response.headers["location"]
        set_cookie = response.headers.get("set-cookie", "")
        assert "oauth_state=" in set_cookie
        assert "oauth_code_verifier=" in set_cookie


@pytest.mark.asyncio
async def test_google_callback_creates_user(unauthed_client: AsyncClient, db_session) -> None:
    """Callback with valid code creates user + returns JWT in body and sets httpOnly cookie."""
    mock_credentials = MagicMock()
    mock_credentials.token = "google_access_token_123"
    mock_credentials.refresh_token = "google_refresh_token_123"
    mock_credentials.expiry = None
    mock_credentials.id_token = "mock_id_token"

    mock_flow = MagicMock()
    mock_flow.credentials = mock_credentials

    id_info = {
        "sub": "google_new_user_456",
        "email": "newuser@test.com",
        "name": "New User",
    }

    with (
        patch("kairos.api.auth._build_flow", return_value=mock_flow),
        patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info),
    ):
        unauthed_client.cookies.set("oauth_state", "state123")
        unauthed_client.cookies.set("oauth_code_verifier", "verifier123")
        response = await unauthed_client.get(
            "/auth/google/callback?code=test_code&state=state123"
        )
        unauthed_client.cookies.clear()

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "access_token" in response.cookies


@pytest.mark.asyncio
async def test_google_callback_existing_user(
    unauthed_client: AsyncClient, db_session, test_user
) -> None:
    """Callback for existing email updates tokens, doesn't duplicate."""
    mock_credentials = MagicMock()
    mock_credentials.token = "updated_access_token"
    mock_credentials.refresh_token = "updated_refresh_token"
    mock_credentials.expiry = None
    mock_credentials.id_token = "mock_id_token"

    mock_flow = MagicMock()
    mock_flow.credentials = mock_credentials

    id_info = {
        "sub": test_user.google_id,
        "email": test_user.email,
        "name": test_user.name,
    }

    with (
        patch("kairos.api.auth._build_flow", return_value=mock_flow),
        patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info),
    ):
        unauthed_client.cookies.set("oauth_state", "state123")
        unauthed_client.cookies.set("oauth_code_verifier", "verifier123")
        response = await unauthed_client.get(
            "/auth/google/callback?code=test_code&state=state123"
        )
        unauthed_client.cookies.clear()

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data

    # Verify tokens were updated
    await db_session.refresh(test_user)
    assert test_user.google_access_token == "updated_access_token"
    assert test_user.google_refresh_token == "updated_refresh_token"


# ── API Key ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_generation(auth_client: AsyncClient) -> None:
    """POST /auth/api-key returns a valid key."""
    response = await auth_client.post("/auth/api-key")
    assert response.status_code == 200
    data = response.json()
    assert "api_key" in data
    assert data["api_key"].startswith("kai_")


@pytest.mark.asyncio
async def test_api_key_authenticates(
    unauthed_client: AsyncClient, db_session, test_user
) -> None:
    """Request with valid API key in header passes auth."""
    from kairos.services.auth_service import generate_api_key

    key = await generate_api_key(db_session, test_user)
    await db_session.commit()

    response = await unauthed_client.get("/auth/me", headers={"X-API-Key": key})
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email


# ── Token validation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_token_returns_401(unauthed_client: AsyncClient) -> None:
    """Request with bad/expired JWT returns 401."""
    response = await unauthed_client.get(
        "/auth/me",
        headers={"Authorization": "Bearer invalid_token_xyz"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_auth_returns_401(unauthed_client: AsyncClient) -> None:
    """Request with no auth header returns 401."""
    response = await unauthed_client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_google_callback_missing_pkce_context_returns_400(
    unauthed_client: AsyncClient,
) -> None:
    """Callback without state/verifier context returns 400 with actionable error."""
    response = await unauthed_client.get(
        "/auth/google/callback?code=test_code&state=state123"
    )
    assert response.status_code == 400
    assert "Missing OAuth PKCE context" in response.json()["detail"]


@pytest.mark.asyncio
async def test_google_callback_state_mismatch_returns_400(
    unauthed_client: AsyncClient,
) -> None:
    """Callback with mismatched state returns 400."""
    unauthed_client.cookies.set("oauth_state", "state_abc")
    unauthed_client.cookies.set("oauth_code_verifier", "verifier123")
    response = await unauthed_client.get(
        "/auth/google/callback?code=test_code&state=state_xyz"
    )
    unauthed_client.cookies.clear()
    assert response.status_code == 400
    assert "Invalid OAuth state" in response.json()["detail"]


@pytest.mark.asyncio
async def test_valid_jwt_authenticates(
    unauthed_client: AsyncClient, db_session, test_user
) -> None:
    """Request with valid JWT passes auth and returns user info."""
    token = create_access_token(test_user.id)
    response = await unauthed_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email
    assert data["id"] == test_user.id


@pytest.mark.asyncio
async def test_cookie_authenticates(
    unauthed_client: AsyncClient, db_session, test_user
) -> None:
    """Request with valid JWT in httpOnly cookie passes auth."""
    token = create_access_token(test_user.id)
    unauthed_client.cookies.set("access_token", token)
    response = await unauthed_client.get("/auth/me")
    unauthed_client.cookies.clear()
    assert response.status_code == 200
    assert response.json()["id"] == test_user.id


@pytest.mark.asyncio
async def test_logout_clears_cookie(unauthed_client: AsyncClient) -> None:
    """POST /auth/logout returns 204 and clears the access_token cookie."""
    response = await unauthed_client.post("/auth/logout")
    assert response.status_code == 204
    # Set-Cookie header with max-age=0 or empty value indicates cookie deletion
    set_cookie = response.headers.get("set-cookie", "")
    assert "access_token" in set_cookie
