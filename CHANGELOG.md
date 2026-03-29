# Kairos Changelog & Session Memory

> **Purpose:** This file is Claude's memory across sessions. Read it at the start of every
> session to understand current project state. Update it at the end of every session with
> what was done, what changed, and what's next.
>
> **Format:** Reverse chronological (newest session first). Each entry is one coding session.

---

## Current State

**Last updated:** 2026-03-29

**Build phase:** Project CRUD complete — ready for Tag CRUD implementation

**What exists:**
- [x] Project scaffold (pyproject.toml, directory structure)
- [x] Docker Compose (PostgreSQL + API)
- [x] Core config + database setup
- [x] SQLAlchemy models (all core models defined)
- [x] Pydantic schemas (Create/Update/Response for all entities)
- [x] Alembic initial migration (generated + applied to local PostgreSQL)
- [x] Auth (Google OAuth + API key + JWT)
- [x] Task CRUD (fully wired — service + routes + 29 tests)
- [x] Project CRUD (fully wired — service + routes + 21 tests)
- [ ] Tag system (route stubs exist, service logic not wired)
- [ ] View system (route stubs exist, service logic not wired)
- [ ] GCal integration (read free/busy, write events)
- [ ] Scheduling engine
- [ ] Schedule-on-write (auto-schedule on task create/update)
- [ ] Blackout days (route stubs exist, service logic not wired)
- [x] Tests passing (82 tests — 66 previous + 21 project CRUD tests - 5 replaced stubs)
- [ ] OpenAPI docs reviewed

**Known issues:**
- `uv` not installed on this machine — used `python3.12 -m venv` + `pip` instead. README documents `uv` as the recommended approach.

**Blocked on:** Google Cloud project setup (need CLIENT_ID + CLIENT_SECRET) to test live OAuth flow and GCal integration

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

### Session 2026-03-29 — Project CRUD implementation

**What was done:**
- Implemented `kairos/services/project_service.py` — full CRUD: `create_project`,
  `list_projects`, `get_project`, `update_project`, `delete_project`, `list_project_tasks`
- Rewrote `kairos/api/projects.py` — all 6 routes wired with auth + DB deps, proper
  response models and 404 handling. `DELETE` is a soft delete (status → archived, returns 200).
  Added `GET /:id/tasks` sub-resource.
- Updated `kairos/schemas/project.py` — added `metadata_json` alias to `ProjectResponse`
  (same pattern as `TaskResponse`), added embedded `TagResponse`, `TaskSummary` for nested
  tasks, `ProjectWithTasksResponse` for `GET /:id`, and `ProjectListResponse` with pagination
- Replaced stub tests in `tests/test_projects.py` with 21 real CRUD + filter + auth + error tests

**What changed:**
- `kairos/api/projects.py` — fully replaced stubs; `DELETE` returns 200 with archived project
  (was 204 no body); `GET /` returns `ProjectListResponse` (was `[]`)
- `kairos/schemas/project.py` — `ProjectResponse.metadata` now uses
  `validation_alias='metadata_json'`; `tags`, `TaskSummary`, `ProjectWithTasksResponse`,
  `ProjectListResponse` added

**Decisions made:**
- `DELETE /projects/:id` returns 200 with the soft-deleted project (status=archived) — consistent
  with task delete behaviour, more useful than 204
- `delete_project` unlinks tasks via a bulk `UPDATE tasks SET project_id = NULL` (SQLAlchemy
  core `sa_update`) — avoids loading all tasks into memory

**What's next:**
- Implement Tag CRUD (`kairos/services/tag_service.py` + `kairos/api/tags.py`)
  and upgrade `tests/test_tags.py` from stubs to real tests
- After tags: View CRUD

**Issues/blockers discovered:**
- None

### Session 2026-03-29 — Task CRUD implementation

**What was done:**
- Implemented `kairos/services/task_service.py` — full CRUD: `create_task`, `list_tasks`,
  `get_task`, `update_task`, `delete_task`, `complete_task`, `unschedule_task`
- Rewrote `kairos/api/tasks.py` — all 7 routes wired with auth + DB deps, proper
  response models and 404 handling. `DELETE` is a soft delete (status → cancelled, returns 200).
  Added `POST /:id/complete` and `POST /:id/unschedule` routes.
- Updated `kairos/schemas/task.py` — added `buffer_mins` to `TaskCreate`,
  `field_validator` for priority (1–4) and duration_mins (positive), `TagResponse` embedded
  in `TaskResponse`, `metadata` field aliased to `metadata_json` ORM attribute to avoid
  collision with SQLAlchemy's `Base.metadata`, added `TaskListResponse` with pagination fields
- Replaced stub tests in `tests/test_tasks.py` with 29 real CRUD + filter + tag + dependency tests
- Updated `tests/test_health.py` — `test_tasks_endpoint_stub` updated to correctly assert 401
  (tasks now require auth)

**What changed:**
- `kairos/api/tasks.py` — fully replaced stubs; `DELETE` now returns 200 + cancelled task
  (was 204 no body)
- `kairos/schemas/task.py` — `TaskResponse.metadata` now uses `validation_alias='metadata_json'`;
  validators added; `TaskListResponse` added

**Decisions made:**
- `DELETE /tasks/:id` returns 200 with the soft-deleted task (status=cancelled) — more useful
  to callers than a silent 204, and aligns with the testing spec
- `update_task` service fetches the task with `selectinload(Task.tags)` before mutation to
  avoid SQLAlchemy lazy-load MissingGreenlet in async context

**What's next:**
- Implement Project CRUD (`kairos/services/project_service.py` + `kairos/api/projects.py`)
  and upgrade `tests/test_projects.py` from stubs to real tests
- After projects: Tag CRUD, then View CRUD

**Issues/blockers discovered:**
- None

### Session 2026-03-29 — Baseline test suite expansion

**What was done:**
- Added module-level baseline tests for all currently implemented API surfaces:
	- auth, tasks, projects, tags, views, schedule endpoints, blackout-days
- Added OpenAPI route registration test to catch missing router wiring
- Added model guard tests for reserved-name workaround (`metadata_json` attr mapping to DB column `metadata`)
- Added migration guard tests to confirm revision files exist and include core table creation
- Ran full test suite and verified all tests pass (`36 passed`)

**What changed:**
- Expanded test coverage from 2 smoke tests to 36 baseline tests aligned with current scaffold behavior

**Decisions made:**
- For the scaffold phase, use behavior-accurate baseline tests (stub responses + route availability) now, then evolve to full feature tests as services are implemented

**What's next:**
- Implement Task CRUD service logic and upgrade `tests/test_tasks.py` from stub assertions to real CRUD + validation/error-path coverage
- Add DB-backed `/health` endpoint and corresponding integration test

**Issues/blockers discovered:**
- Full spec-level tests in `references/testing.md` remain dependent on unimplemented services (Task CRUD, auth, scheduler, GCal)

### Session 2026-03-29 — Alembic initial migration

**What was done:**
- Started PostgreSQL via Docker (`docker compose up -d db`)
- Ran Alembic autogeneration and created initial revision: `a13aec9b7c6d_initial_schema.py`
- Applied migration successfully (`alembic upgrade head`)
- Verified current revision is at head (`a13aec9b7c6d`)
- Ran tests to confirm no regressions (`2 passed`)

**What changed:**
- Updated ORM field names in `Task` and `Project` from `metadata` to `metadata_json` while keeping DB column name `metadata`
- Reason: SQLAlchemy declarative reserves `metadata`, which blocked model import and Alembic autogeneration

**Decisions made:**
- Keep database column names as `metadata` for API/data-model consistency, but avoid reserved SQLAlchemy attribute names at ORM class level

**What's next:**
- Implement Task CRUD service + route wiring against the migrated schema
- Add a `/health` endpoint that checks DB connectivity
- Begin auth groundwork (Google OAuth dependency wiring)

**Issues/blockers discovered:**
- No new blockers for backend progress

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