# Kairos Changelog & Session Memory

> **Purpose:** This file is Claude's memory across sessions. Read it at the start of every
> session to understand current project state. Update it at the end of every session with
> what was done, what changed, and what's next.
>
> **Format:** Reverse chronological (newest session first). Each entry is one coding session.

---

## Current State

**Last updated:** 2026-03-29

**Build phase:** Schedule-on-write complete — blackout days service next

**What exists:**
- [x] Project scaffold (pyproject.toml, directory structure)
- [x] Docker Compose (PostgreSQL + API)
- [x] Core config + database setup
- [x] SQLAlchemy models (all core models defined)
- [x] Pydantic schemas (Create/Update/Response for all entities)
- [x] Alembic initial migration (generated + applied to local PostgreSQL)
- [x] Auth (Google OAuth + API key + JWT)
- [x] Task CRUD (fully wired — service + routes + 35 tests)
- [x] Project CRUD (fully wired — service + routes + 21 tests)
- [x] Tag system (fully wired — service + routes + 17 tests)
- [x] View system (fully wired — service + routes + 27 tests)
- [x] GCal integration (`gcal_service.py` — free/busy, create/update/delete/list events)
- [x] Scheduling engine (`scheduler.py` — urgency scoring, slot fitting, task splitting, dependency checks)
- [x] Schedule API endpoints (POST /schedule/run, GET /schedule/today, GET /schedule/week, GET /schedule/free-slots)
- [x] Schedule-on-write (auto-schedule on task create/update)
- [ ] Blackout days (route stubs exist, service logic not wired)
- [x] Tests passing (167 tests)
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

### Session 2026-03-29 — Schedule-on-write

**What was done:**
- Added `schedule_single_task` to `kairos/services/scheduler.py` — thin wrapper around
  `run_scheduler` for scheduling a single task; fails open (logs warning, returns False)
  so task creation never blocks on GCal availability.
- Updated `kairos/services/task_service.py`:
  - `create_task` accepts optional `gcal: GCalService | None`. If the new task has
    `schedulable=True` and `duration_mins` set, `schedule_single_task` is called
    immediately and the loaded task includes `scheduled_at`/`gcal_event_id`.
  - `update_task` accepts optional `gcal: GCalService | None` and detects whether any
    scheduling-relevant field changed (`duration_mins`, `deadline`, `priority`,
    `schedulable`, `is_splittable`, `min_chunk_mins`, `buffer_mins`). If yes and the
    task remains schedulable with a duration, `schedule_single_task` is called.
  - Added `_SCHEDULING_FIELDS` constant for the field set.
- Updated `kairos/api/tasks.py` — `POST /tasks` and `PATCH /tasks/:id` now inject
  `GCalService` via `Depends(get_gcal_service)` and pass it to the service functions.
- Fixed latent bug in `kairos/services/scheduler.py`: `_to_utc` helper added.
  SQLite strips timezone info when returning `DateTime(timezone=True)` columns, causing
  `can't subtract offset-naive and offset-aware datetimes` errors. Fixed in
  `calculate_urgency`, `_sort_key`, and `find_best_slot`.
- Added 6 schedule-on-write tests to `tests/test_tasks.py`:
  - `test_create_schedulable_task_with_duration_gets_scheduled`
  - `test_create_task_without_duration_not_auto_scheduled`
  - `test_create_task_with_schedulable_false_not_auto_scheduled`
  - `test_update_task_adding_duration_triggers_schedule`
  - `test_update_task_non_scheduling_field_no_reschedule`
  - `test_create_task_gcal_failure_fails_open`

**What changed:**
- `kairos/services/scheduler.py` — `_to_utc` helper; updated `calculate_urgency`,
  `_sort_key`, `find_best_slot`; added `schedule_single_task` at end of file
- `kairos/services/task_service.py` — `gcal` param on `create_task`/`update_task`,
  `_SCHEDULING_FIELDS` constant, scheduling trigger logic
- `kairos/api/tasks.py` — `GCalService` dependency injected into create/update routes
- `tests/test_tasks.py` — 6 new schedule-on-write tests added (35 total, 167 overall)

**Decisions made:**
- Keep `GCalService` out of `task_service.py` module-level imports (TYPE_CHECKING only)
  to preserve clean module boundary; import done lazily inside functions at runtime.
- Schedule-on-write only triggers on create/update — delete, complete, unschedule
  routes are intentionally unchanged (no reschedule side-effects needed).

**What's next:**
- Wire blackout days service (`kairos/services/blackout_service.py`) — route stubs exist,
  service logic is not yet implemented
- Test live GCal integration once Google Cloud credentials are available

**Issues/blockers discovered:**
- SQLite datetime TZ-stripping was a latent bug in the scheduler (now fixed with `_to_utc`)

### Session 2026-03-29 — GCal integration + scheduling engine

**What was done:**
- Implemented `kairos/services/gcal_service.py` — full `GCalService` class:
  `get_free_busy`, `create_event`, `update_event`, `delete_event`, `get_events`.
  Token refresh handled transparently via `_get_valid_credentials`. `GCalAuthError`
  raised on 401/403 so callers can return a clean 401 to the client.
- Implemented `kairos/services/scheduler.py` — full scheduling engine:
  `calculate_urgency`, `get_free_slots`, `find_best_slot`, `split_task`,
  `can_schedule`, `run_scheduler`. Handles blackout days, work hours, buffer time,
  task splitting across multiple GCal events, dependency checks, conflict retry (×3),
  and fail-open on GCal unavailability.
- Wired `kairos/api/schedule.py` — all 4 endpoints implemented with auth + DB:
  `POST /schedule/run` (full or targeted run), `GET /schedule/today`,
  `GET /schedule/week`, `GET /schedule/free-slots?days=N`.
- Added `get_gcal_service` FastAPI dependency to `kairos/core/deps.py`.
- Updated `kairos/schemas/schedule.py` — added `FreeSlotResponse`, `ScheduledTaskResponse`.
- Created `tests/mocks.py` — `MockGCalService` with `add_busy_slot` helper.
- Updated `tests/conftest.py` — `mock_gcal` fixture; `auth_client` now overrides
  `get_gcal_service` so all API tests use the mock.
- Created `tests/test_gcal_service.py` — 9 tests for mock GCal operations.
- Created `tests/test_scheduler.py` — 22 tests covering urgency scoring, free slot
  computation, slot selection, task splitting, dependency checks, and full integration.
- Rewrote `tests/test_schedule_endpoints.py` — 13 real tests replacing 4 stubs.
  Auth on all endpoints verified. Schedule run, today/week views, free-slots all tested.

**What changed:**
- `kairos/services/gcal_service.py` — implemented from empty stub
- `kairos/services/scheduler.py` — implemented from empty stub
- `kairos/api/schedule.py` — replaced 4 stub routes with real implementations
- `kairos/schemas/schedule.py` — added `FreeSlotResponse`, `ScheduledTaskResponse`
- `kairos/core/deps.py` — added `get_gcal_service` dependency
- `tests/conftest.py` — `mock_gcal` fixture added; `auth_client` now overrides GCal dep
- `tests/test_schedule_endpoints.py` — replaced stub tests with real tests

**Decisions made:**
- `GCalService` uses `asyncio.to_thread` for all Google API calls (sync SDK run in executor)
- `MockGCalService` returns `BusySlot` objects (not dicts) to match the real service contract
- `get_gcal_service` dep injects the current `db` session so token refreshes are persisted

**What's next:**
- Wire schedule-on-write: call `run_scheduler` from `task_service.create_task` /
  `task_service.update_task` when scheduling-relevant fields change
- Implement blackout days service (route stubs already exist in `api/blackout_days.py`)

**Issues/blockers discovered:**
- Live GCal integration untestable until Google Cloud project is configured
  (CLIENT_ID + CLIENT_SECRET). All GCal tests use `MockGCalService`.

### Session 2026-03-29 — View CRUD implementation

**What was done:**
- Implemented `kairos/services/view_service.py` — full CRUD: `create_view`, `list_views`,
  `get_view`, `update_view`, `delete_view`, `execute_view`, `seed_default_views`
- Rewrote `kairos/api/views.py` — all 6 routes wired with auth + DB deps, proper
  response models and 404 handling. `DELETE` is a hard delete (returns 204).
  `GET /:id/tasks` executes the view's `filter_config` and returns matching tasks.
- Updated `kairos/schemas/view.py` — added `Field(min_length=1, max_length=200)` on
  `name`, added `position: int = 0` to `ViewCreate`, added `ViewListResponse`
- Wired `seed_default_views` into `auth_service.get_or_create_user` for new users —
  Today, This Week, Unscheduled, High Priority views created on first OAuth login
- Replaced 6 stub tests in `tests/test_views.py` with 27 real tests

**What changed:**
- `kairos/schemas/view.py` — `ViewCreate.name` now has `min_length=1, max_length=200`;
  `ViewCreate` now has `position` field; added `ViewListResponse`
- `kairos/api/views.py` — fully replaced stubs; all routes wired with auth + DB deps
- `kairos/services/view_service.py` — implemented from empty stub
- `kairos/services/auth_service.py` — `get_or_create_user` seeds default views for new users

**Decisions made:**
- `execute_view` resolves `tags_include`/`tags_exclude` by tag **name** (not ID) — matches
  the data model spec; looks up tag IDs from names then applies AND inclusion / NOT IN exclusion
- `due_within_days` computed as `now + N days` cutoff on `Task.deadline`
- `DELETE /views/:id` returns 204 (hard delete, consistent with tags)
- `seed_default_views` is idempotent — checks existing default view names before creating

**What's next:**
- Implement Blackout Days CRUD (`kairos/services/blackout_service.py` + `kairos/api/blackout_days.py`)
  and upgrade `tests/test_blackout_days.py` from stubs to real tests
- After blackout days: GCal integration + scheduling engine

**Issues/blockers discovered:**
- None

### Session 2026-03-29 — Tag CRUD implementation

**What was done:**
- Implemented `kairos/services/tag_service.py` — full CRUD: `create_tag`, `list_tags`
  (with correlated subquery counts), `update_tag`, `delete_tag`
- Rewrote `kairos/api/tags.py` — all 4 routes wired with auth + DB deps, proper
  response models. `DELETE` is a hard delete (returns 204); `GET /` returns
  `TagListResponse` with `task_count` and `project_count` per tag.
- Updated `kairos/schemas/tag.py` — added `Field(min_length=1, max_length=100)` on
  `name`, `TagWithCountsResponse`, `TagListResponse`
- Replaced 4 stub tests in `tests/test_tags.py` with 17 real CRUD + auth + error tests

**What changed:**
- `kairos/schemas/tag.py` — `TagCreate.name` now has `min_length=1, max_length=100`;
  added `TagWithCountsResponse` and `TagListResponse`
- `kairos/api/tags.py` — fully replaced stubs; `DELETE` returns 204 (hard delete);
  `GET /` returns `TagListResponse`; 409 on duplicate name for create and update
- `kairos/services/tag_service.py` — implemented from empty stub

**Decisions made:**
- `GET /tags` uses correlated scalar subqueries for task/project counts — avoids
  loading all related objects into memory
- `DELETE /tags/:id` is a hard delete (per API contract); ON DELETE CASCADE on junction
  tables handles association cleanup automatically
- 409 returned (not 422) for duplicate tag name — it's a conflict, not a validation error

**What's next:**
- Implement View CRUD (`kairos/services/view_service.py` + `kairos/api/views.py`)
  and upgrade `tests/test_views.py` from stubs to real tests
- After views: Blackout days

**Issues/blockers discovered:**
- None

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