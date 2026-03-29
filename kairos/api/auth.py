"""Auth routes — Google OAuth flow + API key management."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.config import settings
from kairos.core.deps import get_db
from kairos.models.user import User
from kairos.schemas.auth import ApiKeyResponse, TokenResponse, UserResponse
from kairos.services.auth_service import (
    create_access_token,
    generate_api_key,
    get_or_create_user,
)

_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

router = APIRouter()

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]


def _build_flow() -> Flow:
    """Build a Google OAuth flow from env config."""
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow


@router.get("/google/login")
async def google_login() -> RedirectResponse:
    """Redirect to the Google OAuth consent screen.

    Requested scopes: `openid email profile calendar`.
    After consent, Google redirects to `GET /auth/google/callback`.
    This endpoint does **not** require authentication.
    """
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/google/callback", response_model=TokenResponse)
async def google_callback(
    code: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Handle the Google OAuth callback.

    Exchanges the authorization `code` for tokens, creates or updates the user record,
    sets a signed JWT as an httpOnly cookie, and returns the token in the body.
    The cookie is the primary auth mechanism for browser clients (`credentials: "include"`).
    API clients may also use the returned token as `Authorization: Bearer <token>`.
    This endpoint does **not** require prior authentication.
    """
    flow = _build_flow()

    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange authorization code: {exc}",
        ) from exc

    credentials = flow.credentials

    # Get user info from Google
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request

    try:
        id_info = id_token.verify_oauth2_token(
            credentials.id_token,
            Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to verify Google token: {exc}",
        ) from exc

    token_expiry = (
        datetime.fromtimestamp(credentials.expiry.timestamp(), tz=timezone.utc)
        if credentials.expiry
        else None
    )

    user = await get_or_create_user(
        db,
        email=id_info["email"],
        name=id_info.get("name"),
        google_id=id_info["sub"],
        access_token=credentials.token,
        refresh_token=credentials.refresh_token,
        token_expiry=token_expiry,
    )

    jwt_token = create_access_token(user.id)
    response.set_cookie(
        key="access_token",
        value=jwt_token,
        httponly=True,
        max_age=_COOKIE_MAX_AGE,
        samesite="lax",
        secure=settings.KAIROS_ENV == "production",
        path="/",
    )
    return TokenResponse(access_token=jwt_token)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    """Clear the auth cookie.

    Deletes the `access_token` httpOnly cookie. The client is responsible for
    discarding any in-memory copy of the token. This endpoint does **not** require
    prior authentication — calling it when already logged out is a no-op.
    """
    response.delete_cookie(key="access_token", httponly=True, samesite="lax", path="/")


@router.post("/api-key", response_model=ApiKeyResponse)
async def create_api_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiKeyResponse:
    """Generate a new API key for agent or automation access.

    The key is prefixed `kairos_sk_` and can be used as a Bearer token.
    Calling this endpoint **replaces** any previously issued API key for this user.
    """
    key = await generate_api_key(db, current_user)
    return ApiKeyResponse(api_key=key)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the currently authenticated user's profile."""
    return UserResponse.model_validate(current_user)
