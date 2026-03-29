from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kairos.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=(settings.KAIROS_ENV == "development"))

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
