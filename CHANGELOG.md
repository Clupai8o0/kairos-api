# Kairos Changelog & Session Memory

> **Purpose:** This file is Claude's memory across sessions. Read it at the start of every
> session to understand current project state. Update it at the end of every session with
> what was done, what changed, and what's next.
>
> **Format:** Reverse chronological (newest session first). Each entry is one coding session.

---

## Current State

**Last updated:** 2026-03-29

**Build phase:** Scaffold complete — ready for Task CRUD implementation

**What exists:**
- [x] Project scaffold (pyproject.toml, directory structure)
- [x] Docker Compose (PostgreSQL + API)
- [x] Core config + database setup
- [x] SQLAlchemy models (all 7 models defined, no migration yet)
- [x] Pydantic schemas (Create/Update/Response for all entities)
- [ ] Alembic initial migration (models exist, migration not yet generated — needs running DB)
- [ ] Auth (Google OAuth + API key)
- [ ] Task CRUD (route stubs exist, service logic not wired)
- [ ] Project CRUD (route stubs exist, service logic not wired)
- [ ] Tag system (route stubs exist, service logic not wired)
- [ ] View system (route stubs exist, service logic not wired)
- [ ] GCal integration (read free/busy, write events)
- [ ] Scheduling engine
- [ ] Schedule-on-write (auto-schedule on task create/update)
- [ ] Blackout days (route stubs exist, service logic not wired)
- [x] Tests passing (2 stub tests — OpenAPI docs load + tasks endpoint returns [])
- [ ] OpenAPI docs reviewed

**Known issues:**
- `uv` not installed on this machine — used `python3.12 -m venv` + `pip` instead. README documents `uv` as the recommended approach.
- Alembic initial migration not yet generated (needs a running PostgreSQL instance via `docker compose up -d db`)

**Blocked on:** Google Cloud project setup (need CLIENT_ID + CLIENT_SECRET) for auth and GCal integration

---

## Active Decisions

> Decisions made during development that aren't in `architecture-decisions.md`.
> If a decision here contradicts an ADR, this file wins (it's newer).

_None yet._

---

## Session Log

<!-- 
TEMPLATE — Copy this block for each session:

### Session YYYY-MM-DD — [Brief description]

**What was done:**
- Item 1
- Item 2

**What changed (if any prior work was modified):**
- Changed X because Y

**Decisions made:**
- Decided to use Z instead of W because [reason]

**What's next:**
- Immediate next step
- Following step

**Issues/blockers discovered:**
- Issue description

-->

### Session 2026-03-29 — Project scaffold

**What was done:**
- Created full project scaffold following `references/project-structure.md` build order (steps 1–2)
- Root config: `pyproject.toml`, `docker-compose.yml`, `Dockerfile`, `.env.example`, `.gitignore`
- Core modules: `config.py` (pydantic-settings), `database.py` (async engine + session factory), `deps.py` (get_db), `auth.py` (stub)
- All 7 SQLAlchemy models: User, Task, Project, Tag (+ junction tables), View, BlackoutDay, ScheduleLog
- All Pydantic schemas: Create/Update/Response for Task, Project, Tag, View, BlackoutDay, Schedule, Auth
- API layer: 33 stub routes across 7 routers (tasks, projects, tags, views, schedule, blackout-days, auth)
- Service layer: 7 stub service modules
- Utils: CUID generator, timezone helpers
- Alembic config: `alembic.ini`, async `migrations/env.py`, `script.py.mako`
- `main.py`: App factory with CORS middleware, lifespan, `/api/v1` prefix
- Test scaffolding: `conftest.py` with httpx AsyncClient fixture, 2 passing stub tests
- Created `README.md` with full setup instructions, Google Cloud setup guide, common commands

**What changed:**
- N/A — first session, greenfield project

**Decisions made:**
- Used `python3.12 -m venv` + `pip` for local setup since `uv` is not installed. `uv` remains the documented/recommended approach in README.
- Used UUID4 with `c` prefix for CUID generation (simple, no external dependency)
- CORS configured from comma-separated env var (`CORS_ORIGINS`)
- All routes are stubs returning empty lists/dicts — services not yet wired

**What's next:**
- Start PostgreSQL via `docker compose up -d db`
- Generate Alembic initial migration (`alembic revision --autogenerate -m "initial schema"`)
- Apply migration (`alembic upgrade head`)
- Wire up Task CRUD through the service layer (build order step 6)
- Add a `/health` endpoint that checks DB connectivity

**Issues/blockers discovered:**
- None blocking progress. Google Cloud credentials needed before auth/GCal work (build order steps 5, 10).