import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kairos.main import create_app
from kairos.models.base import Base
from kairos.models.user import User
from kairos.core.deps import get_db

TEST_DATABASE_URL = "sqlite+aiosqlite://"  # in-memory


# ── SQLite compat: render JSONB as JSON ──────────────────────────────

from sqlalchemy.dialects.postgresql import ARRAY, JSONB

# Override PostgreSQL-specific types so SQLite can handle them
@event.listens_for(Base.metadata, "before_create")
def _remap_pg_types(target, connection, **kw):
    """Swap JSONB → JSON and ARRAY → JSON for SQLite compatibility."""
    for table in target.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            elif isinstance(col.type, ARRAY):
                col.type = JSON()


# ── Simple client (no DB, for stub route tests) ──────────────────────

@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── DB-backed fixtures (for feature tests that need persistence) ─────

@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_user(db_session):
    """Create a default test user in the DB."""
    user = User(
        id="test_user_1",
        email="sam@test.com",
        name="Sam",
        google_id="google_123",
        preferences={
            "work_hours": {"start": "09:00", "end": "17:00"},
            "buffer_mins": 15,
            "default_duration_mins": 60,
            "scheduling_horizon_days": 14,
            "calendar_id": "primary",
            "timezone": "Australia/Melbourne",
        },
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ── Mock GCal fixture ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def mock_gcal():
    """Return a fresh MockGCalService for each test."""
    from tests.mocks import MockGCalService
    return MockGCalService()


# ── Auth + DB + GCal client ──────────────────────────────────────────

@pytest_asyncio.fixture
async def auth_client(db_session, test_user, mock_gcal):
    """Async test client with DB override + auth override + mock GCal."""
    from kairos.core.auth import get_current_user
    from kairos.core.deps import get_gcal_service

    app = create_app()

    async def override_db():
        yield db_session

    async def override_auth():
        return test_user

    def override_gcal():
        return mock_gcal

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_auth
    app.dependency_overrides[get_gcal_service] = override_gcal

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api/v1",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def unauthed_client(db_session):
    """Async test client with DB override but NO auth override — for testing 401s."""
    app = create_app()

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api/v1",
    ) as c:
        yield c
