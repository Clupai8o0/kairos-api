# Kairos Project Structure

## Directory Layout

```
kairos-backend/
├── README.md
├── pyproject.toml              # Project metadata, dependencies (use uv or poetry)
├── alembic.ini                 # Alembic config
├── docker-compose.yml          # PostgreSQL + API for local dev
├── Dockerfile                  # API container
├── .env.example                # Template for environment variables
├── .env                        # Local env (gitignored)
│
├── kairos/                     # Main application package
│   ├── __init__.py
│   ├── main.py                 # FastAPI app factory, lifespan, router mounting
│   │
│   ├── core/                   # Cross-cutting concerns
│   │   ├── __init__.py
│   │   ├── config.py           # Settings from env vars (pydantic-settings)
│   │   ├── database.py         # Async engine, session factory
│   │   ├── auth.py             # OAuth + API key middleware, get_current_user
│   │   └── deps.py             # FastAPI dependency injection (db session, auth)
│   │
│   ├── models/                 # SQLAlchemy ORM models
│   │   ├── __init__.py         # Re-export all models (for Alembic)
│   │   ├── base.py             # Base class, common mixins
│   │   ├── user.py
│   │   ├── task.py
│   │   ├── project.py
│   │   ├── tag.py
│   │   ├── view.py
│   │   ├── blackout_day.py
│   │   └── schedule_log.py
│   │
│   ├── schemas/                # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── task.py             # TaskCreate, TaskUpdate, TaskResponse
│   │   ├── project.py
│   │   ├── tag.py
│   │   ├── view.py
│   │   ├── schedule.py         # ScheduleRunRequest, ScheduleRunResponse
│   │   ├── blackout_day.py
│   │   └── auth.py
│   │
│   ├── api/                    # Route handlers (thin controllers)
│   │   ├── __init__.py
│   │   ├── router.py           # Aggregates all sub-routers
│   │   ├── tasks.py
│   │   ├── projects.py
│   │   ├── tags.py
│   │   ├── views.py
│   │   ├── schedule.py
│   │   ├── blackout_days.py
│   │   └── auth.py
│   │
│   ├── services/               # Business logic layer
│   │   ├── __init__.py
│   │   ├── task_service.py     # CRUD + scheduling trigger
│   │   ├── project_service.py
│   │   ├── tag_service.py
│   │   ├── view_service.py
│   │   ├── scheduler.py        # THE scheduling engine
│   │   ├── gcal_service.py     # Google Calendar API wrapper
│   │   └── blackout_service.py
│   │
│   └── utils/                  # Helpers
│       ├── __init__.py
│       ├── cuid.py             # CUID generation
│       └── time.py             # Timezone helpers, work hours utils
│
├── migrations/                 # Alembic migrations
│   ├── env.py
│   ├── versions/
│   └── script.py.mako
│
└── tests/
    ├── __init__.py
    ├── conftest.py             # Fixtures: test DB, test client, mock GCal
    ├── test_tasks.py
    ├── test_projects.py
    ├── test_tags.py
    ├── test_views.py
    ├── test_scheduler.py       # Critical — most complex logic lives here
    └── test_gcal_service.py
```

---

## Setup Instructions

### Prerequisites
- Python 3.12+
- PostgreSQL 16+
- Docker + Docker Compose (recommended for local dev)
- Google Cloud project with Calendar API enabled + OAuth credentials

### Quick Start

```bash
# Clone and enter
git clone <repo> kairos-backend
cd kairos-backend

# Create virtual environment (using uv — fast)
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -e ".[dev]"

# Copy env template
cp .env.example .env
# Edit .env with your values

# Start PostgreSQL (via Docker)
docker-compose up -d db

# Run migrations
alembic upgrade head

# Start dev server
uvicorn kairos.main:app --reload --port 8000

# Run tests
pytest -v
```

### Environment Variables

```bash
# .env.example

# App
KAIROS_ENV=development          # development | test | production
KAIROS_SECRET_KEY=your-secret   # For JWT signing
KAIROS_API_PORT=8000

# Database
DATABASE_URL=postgresql+asyncpg://kairos:kairos@localhost:5432/kairos

# Google OAuth
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback

# Optional
LOG_LEVEL=DEBUG
CORS_ORIGINS=http://localhost:3000,https://kairos.clupai.com
```

---

## Docker Compose

```yaml
# docker-compose.yml
version: "3.9"

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: kairos
      POSTGRES_PASSWORD: kairos
      POSTGRES_DB: kairos
    ports:
      - "5432:5432"
    volumes:
      - kairos_db:/var/lib/postgresql/data

  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://kairos:kairos@db:5432/kairos
    depends_on:
      - db
    volumes:
      - .:/app
    command: uvicorn kairos.main:app --reload --host 0.0.0.0 --port 8000

volumes:
  kairos_db:
```

---

## Dependency Management

Use `pyproject.toml` with `uv` (preferred) or `poetry`.

### Core Dependencies
```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy[asyncio]>=2.0.30
asyncpg>=0.29.0
alembic>=1.13.0
pydantic>=2.7.0
pydantic-settings>=2.3.0
python-jose[cryptography]>=3.3.0    # JWT
httpx>=0.27.0                        # Async HTTP client (GCal API)
google-auth>=2.29.0
google-auth-oauthlib>=1.2.0
google-api-python-client>=2.130.0
```

### Dev Dependencies
```
pytest>=8.2.0
pytest-asyncio>=0.23.0
httpx>=0.27.0                        # Test client
ruff>=0.4.0                          # Linting + formatting
mypy>=1.10.0                         # Type checking
```

---

## Key Patterns

### App Factory (main.py)
```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

from kairos.core.config import settings
from kairos.core.database import engine
from kairos.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Kairos",
        description="AI-native scheduling API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
```

### Database Session Dependency (deps.py)
```python
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from kairos.core.database import async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### Route → Service Pattern
```python
# api/tasks.py (thin)
@router.post("/", response_model=TaskResponse, status_code=201)
async def create_task(
    task_in: TaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await task_service.create(db, user, task_in)


# services/task_service.py (logic lives here)
async def create(db: AsyncSession, user: User, task_in: TaskCreate) -> Task:
    task = Task(user_id=user.id, **task_in.model_dump(exclude={"tag_ids"}))
    # ... handle tags, save, trigger scheduler ...
    return task
```

---

## Build Order (v1)

Build in this order — each step depends on the previous:

1. **Project scaffold** — pyproject.toml, directory structure, Docker Compose
2. **Core: config + database** — Settings, engine, session factory
3. **Models** — All SQLAlchemy models + Alembic initial migration
4. **Schemas** — Pydantic schemas for all endpoints
5. **Auth** — Google OAuth flow + API key generation
6. **Task CRUD** — Full CRUD endpoints + tests
7. **Project CRUD** — Full CRUD + tests
8. **Tag system** — CRUD + assignment to tasks/projects
9. **View system** — CRUD + filter execution
10. **GCal integration** — Read free/busy, write events, delete events
11. **Scheduling engine** — The core algorithm (references/scheduling-engine.md)
12. **Schedule-on-write** — Wire scheduler into task creation/update
13. **Blackout days** — CRUD + scheduler integration
14. **Schedule endpoints** — /schedule/run, /schedule/today, /schedule/week, /free-slots
15. **Polish** — Error handling, logging, OpenAPI docs review