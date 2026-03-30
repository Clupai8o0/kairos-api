from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.database import async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        # Ensure each request runs in a managed transaction that is committed
        # or rolled back exactly once.
        async with session.begin():
            yield session


def get_gcal_service(db: AsyncSession = Depends(get_db)) -> "GCalService":  # type: ignore[return]
    """FastAPI dependency — returns a GCalService instance wired to the current DB session."""
    from kairos.services.gcal_service import GCalService
    return GCalService(db=db)
