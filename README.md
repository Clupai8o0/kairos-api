# Kairos

AI-native scheduling and task management API. The backend engine for the Clupai ecosystem.

Tasks go in. The engine decides when they happen. Google Calendar reflects reality.

> **This repo is purely the backend API.** There is no frontend, no UI, no web interface.
> You interact with Kairos through HTTP requests (curl, Postman, Swagger UI at `/docs`,
> or programmatically via OpenClaw/agents). The frontend will be a **separate repository**
> that consumes this API and lives at `kairos.clupai.com`.

---

## What This Does

Kairos is a single REST API that handles task creation, project management, tagging, saved views, and automatic scheduling into Google Calendar. It's designed to be consumed by multiple clients — a frontend app (future), OpenClaw agents, n8n workflows, CLI scripts — without any frontend-specific assumptions. There is no HTML, no templates, no server-side rendering. Every endpoint returns JSON.

**Core features (v1):**
- Task and project CRUD with flexible metadata
- Universal tag system (replaces categories, contexts, areas)
- Saved views (reusable filter configurations)
- Auto-scheduling engine that slots tasks into Google Calendar free time
- Schedule-on-write — creating a task automatically schedules it
- Unified schedule reads across linked Google accounts/calendars (day/week)
- Direct Google Calendar event creation API (`POST /events`)
- Calendar event details + in-app event editing APIs (`/calendar/*`)
- Blackout days (days where nothing gets scheduled)

---

## Prerequisites

### Required Software

| Tool | Version | What it's for |
|------|---------|---------------|
| **Python** | 3.12+ | Runtime |
| **uv** | latest | Python package manager (fast pip replacement) |
| **Docker Desktop** | latest | Runs PostgreSQL locally |
| **Git** | latest | Version control |

### Required Accounts / Credentials

| Service | What you need | How to get it |
|---------|---------------|---------------|
| **Google Cloud** | OAuth Client ID + Secret | See [Google Cloud Setup](#google-cloud-setup) below |

### Optional (recommended)

| Tool | What it's for |
|------|---------------|
| **Homebrew** | Installing everything else on macOS |
| **pgAdmin** or **DBeaver** | Visual database browser |
| **Postman** or **Bruno** | API testing (or just use the auto-generated Swagger UI at `/docs`) |

---

## Installation

### 1. Install system dependencies (macOS / Apple Silicon)

```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.12+
brew install python@3.12

# Install uv (fast Python package manager)
brew install uv

# Install Docker Desktop
# Download from: https://www.docker.com/products/docker-desktop/
# Or: brew install --cask docker

# Verify installations
python3 --version    # Should be 3.12+
uv --version
docker --version
docker compose version`
```

> **Note:** You do NOT need to install PostgreSQL locally. Docker handles it.
> You do NOT need to install Node.js — this is a Python project.

### 2. Clone and set up the project

```bash
# Clone the repo
git clone <your-repo-url> kairos-backend
cd kairos-backend

# Create virtual environment
uv venv
source .venv/bin/activate

# Install all dependencies (including dev tools)
uv pip install -e ".[dev]"
```

### 3. Set up environment variables

```bash
# Copy the template
cp .env.example .env

# Edit with your values
# At minimum you need:
#   - DATABASE_URL (pre-filled for Docker setup)
#   - GOOGLE_CLIENT_ID
#   - GOOGLE_CLIENT_SECRET
#   - FRONTEND_URL (where OAuth callback should redirect after successful login, e.g. http://localhost:3000/)
#   - KAIROS_SECRET_KEY (generate one: python -c "import secrets; print(secrets.token_urlsafe(32))")
```

### 4. Start PostgreSQL

```bash
# Start the database container
docker compose up -d db

# Verify it's running
docker compose ps
# Should show: kairos-db running on port 5432
```

### 5. Run database migrations

```bash
# Apply all migrations
alembic upgrade head

# Verify
alembic current
```

### 6. Start the API

```bash
# Development mode (auto-reload on file changes)
uvicorn kairos.main:app --reload --port 8000

# API is now running at: http://localhost:8000
# Swagger UI docs at:    http://localhost:8000/docs
# ReDoc at:              http://localhost:8000/redoc
```

### 7. Verify everything works

```bash
# Check API is responding (Swagger UI)
open http://localhost:8000/docs

# Or test a stub endpoint
curl http://localhost:8000/api/v1/tasks/
# Should return: []
```

---

## Google Cloud Setup

You need a Google Cloud project with Calendar API enabled to use scheduling features.

### Step-by-step

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (name it "Kairos" or whatever you want)
3. Enable the **Google Calendar API**:
   - Go to APIs & Services → Library
   - Search "Google Calendar API"
   - Click Enable
4. Create OAuth credentials:
   - Go to APIs & Services → Credentials
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: **Web application**
   - Name: "Kairos Local"
   - Authorized redirect URIs: `http://localhost:8000/api/v1/auth/google/callback`
   - Click Create
5. Copy the **Client ID** and **Client Secret** into your `.env` file
6. Configure the OAuth consent screen:
   - Go to APIs & Services → OAuth consent screen
   - User type: **External** (for development)
   - Add your email as a test user
   - Add scopes: `openid`, `email`, `profile`, `Google Calendar API (../auth/calendar)`

> **Important:** While the app is in "Testing" mode, only test users you've added
> can authenticate. This is fine for personal use.

---

## Common Commands

```bash
# Start everything (DB + API)
docker compose up -d db && uvicorn kairos.main:app --reload --port 8000

# Stop the database
docker compose down

# Stop and delete all data (fresh start)
docker compose down -v

# Run tests
pytest -v

# Run tests with coverage
pytest --cov=kairos --cov-report=term-missing

# Create a new migration after changing models
alembic revision --autogenerate -m "description of change"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Lint and format
ruff check .
ruff format .

# Type check
mypy kairos/
```

---

## Project Structure

```
kairos-api/
├── kairos/                     # Main application package
│   ├── main.py                 # FastAPI app factory
│   ├── core/                   # Config, database, auth, dependencies
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response schemas
│   ├── api/                    # Route handlers (thin controllers)
│   ├── services/               # Business logic layer
│   └── utils/                  # Helpers (CUID generation, time utils)
├── migrations/                 # Alembic database migrations
├── references/                 # Architecture docs and reference specs
├── tests/                      # Test suite
├── docker-compose.yml          # Local dev infrastructure
├── pyproject.toml              # Dependencies and project config
└── .env                        # Environment variables (gitignored)
```

For the complete file-level breakdown, see `references/project-structure.md`.

---

## Architecture

- **FastAPI** — async Python web framework with auto-generated OpenAPI docs
- **SQLAlchemy 2.0** (async) — ORM with full type hint support
- **PostgreSQL 16** — relational database with JSONB for flexible metadata
- **Google Calendar API v3** — source of truth for time blocks
- **Pydantic v2** — request/response validation

The API follows a strict layered pattern: Routes → Services → Models. Routes are thin controllers that delegate to services. Services contain all business logic. Models never import from services.

Full architecture decisions are documented in `references/architecture-decisions.md`.

---

## API Documentation

Once the server is running, interactive API docs are available at:

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

The full API contract is documented in `references/api-contract.md`.

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12+ |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Database | PostgreSQL 16 |
| Auth | Google OAuth 2.0 + API keys |
| Calendar | Google Calendar API v3 |
| Validation | Pydantic v2 |
| Testing | pytest + httpx |
| Linting | ruff |
| Type checking | mypy |
| Containers | Docker + Docker Compose |
| Package manager | uv |

---

## License

Private project. Not open source.