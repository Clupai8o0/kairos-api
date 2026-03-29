"""Authentication dependencies — JWT Bearer token + API key auth."""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.deps import get_db
from kairos.models.user import User
from kairos.services.auth_service import decode_access_token, get_user_by_api_key, get_user_by_id

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    api_key: str | None = Security(api_key_header),
) -> User:
    """Resolve the current user from either a Bearer JWT or X-API-Key header.

    Priority: Bearer token > API key. Returns 401 if neither is valid.
    """
    # Try Bearer JWT first
    if credentials is not None:
        user_id = decode_access_token(credentials.credentials)
        if user_id is not None:
            user = await get_user_by_id(db, user_id)
            if user is not None:
                return user

    # Try API key
    if api_key is not None:
        user = await get_user_by_api_key(db, api_key)
        if user is not None:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
