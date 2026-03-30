"""Authentication service — JWT tokens, Google OAuth exchange, API key management."""

import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.config import settings
from kairos.models.google_account import GoogleAccount
from kairos.models.user import User

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def create_access_token(user_id: str) -> str:
    """Create a JWT access token for a user."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.KAIROS_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Decode a JWT and return the user_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.KAIROS_SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


async def get_or_create_user(
    db: AsyncSession,
    *,
    email: str,
    name: str | None,
    google_id: str,
    access_token: str,
    refresh_token: str | None,
    token_expiry: datetime | None,
    existing_user_id: str | None = None,
) -> User:
    """Find user by google_id or email, or create a new one. Update Google tokens."""
    user: User | None = None

    if existing_user_id:
        result = await db.execute(select(User).where(User.id == existing_user_id))
        user = result.scalar_one_or_none()

    if user is None:
        result = await db.execute(select(User).where(User.google_id == google_id))
        user = result.scalar_one_or_none()

    if user is None:
        # Check by email as fallback (user may have been pre-created)
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

    if user is None:
        user = User(
            email=email,
            name=name,
            google_id=google_id,
            google_access_token=access_token,
            google_refresh_token=refresh_token,
            google_token_expiry=token_expiry,
            preferences={
                "work_hours": {"start": "09:00", "end": "17:00"},
                "buffer_mins": 15,
                "default_duration_mins": 60,
                "scheduling_horizon_days": 14,
                "calendar_id": "primary",
                "timezone": "Australia/Melbourne",
            },
        )
        db.add(user)
        await db.flush()
        from kairos.services import view_service
        await view_service.seed_default_views(db, user)
    else:
        user.google_id = google_id
        user.google_access_token = access_token
        if refresh_token:
            user.google_refresh_token = refresh_token
        user.google_token_expiry = token_expiry
        if name:
            user.name = name

    await db.flush()
    return user


async def upsert_google_account(
    db: AsyncSession,
    *,
    user: User,
    google_account_id: str,
    email: str,
    display_name: str | None,
    access_token: str,
    refresh_token: str | None,
    token_expiry: datetime | None,
    scopes: list[str] | None,
) -> GoogleAccount:
    """Create or update a linked Google account for the user."""
    result = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.user_id == user.id,
            GoogleAccount.google_account_id == google_account_id,
        )
    )
    account = result.scalar_one_or_none()

    if account is None:
        existing = await db.execute(
            select(GoogleAccount).where(GoogleAccount.user_id == user.id)
        )
        has_existing = existing.scalar_one_or_none() is not None
        account = GoogleAccount(
            user_id=user.id,
            google_account_id=google_account_id,
            email=email,
            display_name=display_name,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
            scopes=scopes or [],
            is_primary=not has_existing,
        )
        db.add(account)
    else:
        account.email = email
        if display_name:
            account.display_name = display_name
        account.access_token = access_token
        if refresh_token:
            account.refresh_token = refresh_token
        account.token_expiry = token_expiry
        account.scopes = scopes or account.scopes

    await db.flush()
    return account


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    """Look up a user by primary key."""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_api_key(db: AsyncSession, api_key: str) -> User | None:
    """Look up a user by API key."""
    result = await db.execute(select(User).where(User.api_key == api_key))
    return result.scalar_one_or_none()


async def generate_api_key(db: AsyncSession, user: User) -> str:
    """Generate and store a new API key for the user, replacing any existing one."""
    key = f"kai_{secrets.token_urlsafe(32)}"
    user.api_key = key
    await db.flush()
    return key
