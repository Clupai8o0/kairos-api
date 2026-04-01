"""Auth routes — Google OAuth flow + API key management."""

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.config import settings
from kairos.core.deps import get_db
from kairos.models.user import User
from kairos.schemas.auth import ApiKeyResponse, PreferencesResponse, PreferencesUpdate, UserResponse
from kairos.services.auth_service import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    get_or_create_user,
    get_user_by_id,
    upsert_google_account,
)

_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
_OAUTH_COOKIE_MAX_AGE = 60 * 10  # 10 minutes
_OAUTH_STATE_COOKIE = "oauth_state"
_OAUTH_VERIFIER_COOKIE = "oauth_code_verifier"

router = APIRouter()

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]


def _build_flow(state: str | None = None) -> Flow:
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
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state,
        autogenerate_code_verifier=True,
    )
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
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        code_challenge_method="S256",
    )
    if not flow.code_verifier:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate PKCE verifier for OAuth flow",
        )

    redirect = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key=_OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        max_age=_OAUTH_COOKIE_MAX_AGE,
        samesite="lax",
        secure=settings.KAIROS_ENV == "production",
        path="/",
    )
    redirect.set_cookie(
        key=_OAUTH_VERIFIER_COOKIE,
        value=flow.code_verifier,
        httponly=True,
        max_age=_OAUTH_COOKIE_MAX_AGE,
        samesite="lax",
        secure=settings.KAIROS_ENV == "production",
        path="/",
    )
    return redirect


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    access_token: str | None = Cookie(default=None),
    oauth_state: str | None = Cookie(default=None, alias=_OAUTH_STATE_COOKIE),
    oauth_code_verifier: str | None = Cookie(default=None, alias=_OAUTH_VERIFIER_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle the Google OAuth callback.

    Exchanges the authorization `code` for tokens, creates or updates the user record,
    sets a signed JWT as an httpOnly cookie, then redirects the browser to the frontend.
    The cookie is the primary auth mechanism for browser clients (`credentials: "include"`).
    This endpoint does **not** require prior authentication.
    """
    if oauth_state is None or oauth_code_verifier is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Missing OAuth PKCE context. Start auth from /auth/google/login "
                "in the same browser session."
            ),
        )

    if not hmac.compare_digest(oauth_state, state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state. Please retry login.",
        )

    flow = _build_flow(state=state)
    flow.code_verifier = oauth_code_verifier

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
    raw_scopes = getattr(credentials, "scopes", None)
    scope_list = list(raw_scopes) if isinstance(raw_scopes, (list, tuple, set)) else []

    existing_user_id: str | None = None
    if access_token:
        existing_user_id = decode_access_token(access_token)
        if existing_user_id:
            existing_user = await get_user_by_id(db, existing_user_id)
            if existing_user is None:
                existing_user_id = None

    user = await get_or_create_user(
        db,
        email=id_info["email"],
        name=id_info.get("name"),
        google_id=id_info["sub"],
        access_token=credentials.token,
        refresh_token=credentials.refresh_token,
        token_expiry=token_expiry,
        existing_user_id=existing_user_id,
    )

    await upsert_google_account(
        db,
        user=user,
        google_account_id=id_info["sub"],
        email=id_info["email"],
        display_name=id_info.get("name"),
        access_token=credentials.token,
        refresh_token=credentials.refresh_token,
        token_expiry=token_expiry,
        scopes=scope_list,
    )

    jwt_token = create_access_token(user.id)
    redirect = RedirectResponse(url=settings.FRONTEND_URL, status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie(key=_OAUTH_STATE_COOKIE, httponly=True, samesite="lax", path="/")
    redirect.delete_cookie(key=_OAUTH_VERIFIER_COOKIE, httponly=True, samesite="lax", path="/")
    redirect.set_cookie(
        key="access_token",
        value=jwt_token,
        httponly=True,
        max_age=_COOKIE_MAX_AGE,
        samesite="lax",
        secure=settings.KAIROS_ENV == "production",
        path="/",
    )
    return redirect


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


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(
    current_user: User = Depends(get_current_user),
) -> PreferencesResponse:
    """Return the current user's scheduling preferences.

    All values written here are used by the scheduling engine:
    - `work_hours` — slots outside this window are never offered
    - `timezone` — IANA timezone the work_hours are interpreted in (e.g. `"Australia/Melbourne"`)
    - `scheduling_horizon_days` — how many days ahead the scheduler looks (default 14)
    - `buffer_mins` — default buffer added after each scheduled task
    - `default_duration_mins` — duration used when a task has no explicit duration
    """
    p = current_user.preferences
    return PreferencesResponse(
        work_hours=p.get("work_hours", {"start": "09:00", "end": "17:00"}),
        timezone=p.get("timezone", "UTC"),
        scheduling_horizon_days=p.get("scheduling_horizon_days", 14),
        buffer_mins=p.get("buffer_mins", 15),
        default_duration_mins=p.get("default_duration_mins", 60),
    )


@router.patch("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    payload: PreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PreferencesResponse:
    """Update the current user's scheduling preferences.

    Send only the fields you want to change. All fields are optional.
    Changes take effect on the next scheduler run — run `POST /schedule/run`
    immediately after if you want tasks rescheduled into the new work window.

    `work_hours.start` and `work_hours.end` must be `HH:MM` in 24-hour format.
    They are interpreted in the user's `timezone`.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from sqlalchemy import inspect as sa_inspect

    if payload.timezone is not None:
        try:
            ZoneInfo(payload.timezone)
        except (KeyError, ZoneInfoNotFoundError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "invalid_timezone", "message": f"Unknown timezone: {payload.timezone}"},
            )

    p = dict(current_user.preferences)
    if payload.work_hours is not None:
        p["work_hours"] = payload.work_hours.model_dump()
    if payload.timezone is not None:
        p["timezone"] = payload.timezone
    if payload.scheduling_horizon_days is not None:
        p["scheduling_horizon_days"] = payload.scheduling_horizon_days
    if payload.buffer_mins is not None:
        p["buffer_mins"] = payload.buffer_mins
    if payload.default_duration_mins is not None:
        p["default_duration_mins"] = payload.default_duration_mins

    current_user.preferences = p
    # Force SQLAlchemy to see the JSONB mutation
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(current_user, "preferences")
    await db.flush()

    return PreferencesResponse(
        work_hours=p.get("work_hours", {"start": "09:00", "end": "17:00"}),
        timezone=p.get("timezone", "UTC"),
        scheduling_horizon_days=p.get("scheduling_horizon_days", 14),
        buffer_mins=p.get("buffer_mins", 15),
        default_duration_mins=p.get("default_duration_mins", 60),
    )
