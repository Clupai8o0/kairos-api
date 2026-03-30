# Kairos Changelog & Session Memory

> **Purpose:** This file is Claude's memory across sessions. Read it at the start of every
> session to understand current project state. Update it at the end of every session with
> what was done, what changed, and what's next.
>
> **Format:** Reverse chronological (newest session first). Each entry is one coding session.

---

## Current State

**Last updated:** 2026-03-30

**Build phase:** Frontend-ready — v1 feature-complete + frontend integration

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
- [x] Blackout days (fully wired — service + routes + 11 tests)
- [x] Tests passing (196 tests)
- [x] OpenAPI docs reviewed

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

### Session 2026-03-30 — Task-backed event controls + calendar-scoped scheduling views

**What was done:**
- Updated schedule endpoints to keep task items visible and control task-backed calendar
  event visibility via query option (`task_events=exclude|include`).
- Added event payload flags for task linkage: `is_task_event` and `task_id`.
- Added calendar scoping options:
  - `GET /schedule/today` and `GET /schedule/week` query `calendar_ids`
  - `GET /schedule/free-slots` query `calendar_ids`
  - `POST /schedule/run` body `calendar_ids`
- Updated Google free/busy behavior to use selected calendars across linked accounts by
  default, with optional calendar ID scoping override.
- Added/updated tests in `tests/test_schedule_endpoints.py` and mock behavior updates in
  `tests/mocks.py` for task-backed event filtering and calendar view scoping.
- Added frontend handover guide: `references/frontend-handover-schedule-views.md`.

**What changed:**
- Duplicate timeline entries are now solved by filtering/flagging event rows instead of
  hiding tasks, preserving task-native editing UX.
- Calendar selection now affects both schedule views and busy-time calculations used by
  scheduling/free-slot endpoints.

**Decisions made:**
- Keep tasks as the primary editable timeline entity.
- Treat task-backed Google events as optional timeline rows with explicit linkage metadata.

**What's next:**
- Frontend to adopt `task_events=exclude` as default and use `calendar_ids` for
  per-view scoping.

**Issues/blockers discovered:**
- None

### Session 2026-03-30 — Schedule feed dedupe for task-backed calendar events

**What was done:**
- Updated `GET /schedule/today` and `GET /schedule/week` to suppress task items when a
  matching Google event exists in the same response window (`task.gcal_event_id == event_id`).
- Added regression tests in `tests/test_schedule_endpoints.py` for both today and week
  responses to verify duplicate suppression.
- Updated `references/api-contract.md` with the dedupe behavior note for both endpoints.

**What changed:**
- Frontend consumers of schedule endpoints now receive one timeline item for synced tasks,
  avoiding task + event double rendering.

**Decisions made:**
- Perform dedupe at the schedule API boundary rather than forcing frontend logic to infer
  task-event equivalence.

**What's next:**
- Consider adding an opt-in query flag to include task rows for debug/admin UIs if needed.

**Issues/blockers discovered:**
- None

### Session 2026-03-30 — All-day Google event handling parity

### Session 2026-03-30 — Fix asyncpg manual transaction collision on request auth/query path

**What was done:**
- Hardened DB engine pooling config with `pool_pre_ping=True` and
  `pool_reset_on_return="rollback"`.
- Updated request DB dependency to use `async with session.begin()` so each request has
  a single managed transaction lifecycle (commit/rollback exactly once).

**What changed:**
- Prevents intermittent `cannot use Connection.transaction() in a manually started transaction`
  errors seen on authenticated request paths (e.g. `POST /tasks`).

**Decisions made:**
- Prefer explicit transaction-scoped request handling over manual commit/rollback in the
  dependency finalizer.

**What's next:**
- Monitor local dev logs after reload cycles to confirm no recurrence.

**Issues/blockers discovered:**
- None

### Session 2026-03-30 — All-day Google event handling parity

**What was done:**
- Updated GCal event parsing to treat date-only payloads as all-day events in the legacy
  `get_events` path (no longer dropped).
- Added shared parsing helper to normalize both timed and all-day Google event windows.
- Updated calendar event patch logic to preserve Google semantics:
  - all-day events patch using `start.date` / `end.date`
  - timed events patch using `start.dateTime` / `end.dateTime`
- Added regression tests in `tests/test_gcal_all_day_support.py` for date/dateTime parsing
  and outbound patch field shape.

**What changed:**
- Backend now consistently accommodates all-day events across schedule mapping and direct
  event listing/update pathways.

**Decisions made:**
- Keep all-day `end` handling exclusive, matching Google Calendar API behavior.

**What's next:**
- Add integration test coverage for editing existing all-day events through the calendar API.

**Issues/blockers discovered:**
- None

### Session 2026-03-30 — Persisted calendar visibility preferences

**What was done:**
- Added persisted per-user calendar visibility selection support via
  `PATCH /calendar/accounts/selection`.
- Added request/response schemas for bulk selection updates and refreshed account payload.
- Updated `GCalService._sync_calendars_for_account` to preserve user `selected` choices for
  existing calendars (provider sync no longer overwrites preferences).
- Added `GCalService.update_calendar_selections` with idempotent behavior and validation for
  unknown account/calendar pairs.
- Updated test mocks and added API tests for:
  - persisted selection after re-fetch
  - idempotent updates (`updated=0` when unchanged)
  - unknown pair validation (`422 unknown_calendar_selection`)

**What changed:**
- `GET /calendar/accounts` now consistently reflects persisted `selected` values.

**Decisions made:**
- Persist selection state in `google_calendars.selected` as the single source of truth for
  schedule filtering visibility.

**What's next:**
- Optionally expose per-calendar ordering/grouping metadata for frontend preferences.

**Issues/blockers discovered:**
- None

### Session 2026-03-30 — Fix schedule/week 500 from Google credential expiry timezone mismatch

**What was done:**
- Fixed `TypeError: can't compare offset-naive and offset-aware datetimes` in
  `GCalService._get_valid_credentials` path used by `GET /schedule/week`.
- Added `GCalService._normalize_google_expiry` and now normalize persisted token expiry
  datetimes to naive UTC before constructing `google.oauth2.credentials.Credentials`.
- Added regression tests in `tests/test_gcal_expiry_normalization.py` covering both
  user-level and linked-account token expiry normalization.

**What changed:**
- No API contract changes; runtime stability fix only.

**Decisions made:**
- Keep DB token expiry timezone-aware for storage, but convert to naive UTC at Google
  credentials boundary to match the library's expectation.

**What's next:**
- Re-run live OAuth + schedule/week browser flow to confirm no further runtime exceptions.

**Issues/blockers discovered:**
- None

### Session 2026-03-30 — Multi-account Google event coverage + calendar edit APIs

**What was done:**
- Added linked Google account/calendar data models:
  - `google_accounts` (per-user linked OAuth accounts + scopes/tokens)
  - `google_calendars` (per-account calendars + access role + selected flag)
- Extended OAuth callback to support linking additional Google accounts to an already
  authenticated Kairos user and persist granted scopes.
- Expanded `GCalService` with:
  - multi-account calendar discovery and short-lived calendar list caching
  - merged event reads across selected calendars/accounts (`get_schedule_events`)
  - event detail fetch + event patch with etag conflict checks
  - ownership checks (account/calendar must belong to current user)
  - retry/backoff for transient Google API failures (`429/500/503` + network)
  - machine-readable permission/scope/conflict/not-found error paths
- Updated schedule endpoints:
  - `GET /schedule/today` and `GET /schedule/week` now merge task items with Google event items
  - event payload includes provider/account/calendar metadata, recurrence flags, html link,
    editability, and etag
  - timezone-aware boundaries with optional range params (`day`, `start_date`, `end_date`)
- Added new calendar endpoints:
  - `GET /calendar/accounts`
  - `GET /calendar/events/{event_id}`
  - `PATCH /calendar/events/{event_id}`
- Added migration `c2b9a4f1c8d7_add_google_accounts_and_calendars.py`.
- Updated docs:
  - `references/api-contract.md`
  - `references/gcal-integration.md`
  - `README.md`

**What changed:**
- Schedule API now returns Google event items in `today/week` responses, not task-only data.
- OAuth callback now attaches newly consented Google accounts to the current logged-in user
  when an auth cookie is present.

**Decisions made:**
- Keep task scheduling behavior unchanged; scheduler still uses primary account behavior for
  schedule-on-write while read/edit APIs aggregate across all linked calendars.
- Use optimistic concurrency for event edits via etag mismatch detection (`409`).

**What's next:**
- Add explicit account-connect/disconnect management endpoints and calendar selection toggles.
- Add staging verification against real Google accounts with mixed scope grants.

**Issues/blockers discovered:**
- Existing migration test assumed the latest migration was always initial schema; updated test to
  target the actual initial migration file so new revisions do not fail CI.

### Session 2026-03-30 — OAuth PKCE state/verifier fix

**What was done:**
- Updated `GET /auth/google/login` in `kairos/api/auth.py` to use PKCE explicitly by generating/storing OAuth `state` and `code_verifier` in short-lived httpOnly cookies (`oauth_state`, `oauth_code_verifier`), and requesting auth URL with `code_challenge_method=S256`.
- Updated `GET /auth/google/callback` in `kairos/api/auth.py` to require `state`, validate cookie-backed PKCE context, verify state match, and set `flow.code_verifier` before token exchange.
- Added explicit 400 errors for missing PKCE context and invalid OAuth state to make local-dev failures diagnosable.
- Cleans up temporary PKCE cookies after successful callback.
- Updated auth tests in `tests/test_auth.py` to include callback `state` and PKCE cookies, and added new failure-path tests:
  - `test_google_callback_missing_pkce_context_returns_400`
  - `test_google_callback_state_mismatch_returns_400`

**What changed:**
- OAuth callback contract now requires the `state` query parameter and valid PKCE context from the same browser session started via `/auth/google/login`.

**Decisions made:**
- Use short-lived, httpOnly cookie storage for PKCE context in v1 (no Redis dependency yet), aligned with current cookie-based browser auth flow.

**What's next:**
- Run a live end-to-end OAuth test against Google Cloud credentials to confirm local frontend signup/login path.
- If cross-origin cookie issues appear, add explicit dev-domain guidance (`localhost` vs `127.0.0.1`) to README troubleshooting.

**Issues/blockers discovered:**
- None

### Session 2026-03-30 — OAuth callback frontend redirect

**What was done:**
- Updated `GET /auth/google/callback` in `kairos/api/auth.py` to redirect to frontend after successful OAuth token exchange, instead of returning JWT JSON in the response body.
- Added `FRONTEND_URL` setting in `kairos/core/config.py` (default: `http://localhost:3000/`).
- Added `FRONTEND_URL` to `.env.example` for local configuration.
- Updated auth tests in `tests/test_auth.py` to assert `302` + `Location: http://localhost:3000/` and retained cookie assertions.
- Updated docs:
  - `references/api-contract.md` now documents `GET /auth/google/login` and callback redirect behavior.
  - `README.md` env setup now includes `FRONTEND_URL`.

**What changed:**
- OAuth callback response contract changed from JSON token payload to browser redirect with auth cookie.

**Decisions made:**
- Browser OAuth flow should complete by landing users back on the frontend root while keeping JWT in an httpOnly API-domain cookie.

**What's next:**
- Verify frontend uses `credentials: "include"` on authenticated API calls so cookie-based auth is sent to backend.
- Optionally add a dedicated frontend route (e.g. `/auth/callback`) and redirect there instead of `/`.

**Issues/blockers discovered:**
- None

### Session 2026-03-29 — Frontend integration: cookie auth + schedule response shape

**What was done:**
- `kairos/api/auth.py`: OAuth callback now sets `access_token` as an httpOnly cookie
  (`secure=True` in production, `samesite=lax`). JWT is still returned in the body for
  non-browser clients. Added `POST /auth/logout` that deletes the cookie (204, no auth required).
- `kairos/core/auth.py`: `get_current_user` now reads JWT from httpOnly cookie
  (`Cookie: access_token`) as a third auth path — after Bearer header, before API key.
  Priority: Bearer > cookie > X-API-Key.
- `kairos/schemas/schedule.py`: Added `ScheduleItem`, `GCalEventItem`, `ScheduleTodayResponse`
  matching the frontend TypeScript types exactly.
- `kairos/api/schedule.py`: `GET /schedule/today` now returns `ScheduleTodayResponse`
  (`{ date, items: [{ type, task }] }`). `GET /schedule/week` now returns
  `list[ScheduleTodayResponse]`, one entry per day with tasks, ordered by date.
  Both endpoints eagerly load tags via `selectinload`.
- Tests updated: 4 new auth tests (cookie auth, logout), schedule tests updated for new shape.
  177 tests total, all passing.

**What changed:**
- `GET /schedule/today` response shape: was `list[ScheduledTaskResponse]`, now
  `ScheduleTodayResponse`. Breaking change for any client using the old shape.
- `GET /schedule/week` response shape: was `list[ScheduledTaskResponse]`, now
  `list[ScheduleTodayResponse]`. Breaking change.

**Decisions made:**
- Cookie is `samesite=lax` (not `strict`) so it's sent on top-level navigations
  (e.g. Google redirecting back to our app after OAuth).
- `/schedule/week` omits days with no tasks rather than returning empty-items days —
  cleaner for the frontend to render.
- `ScheduledTaskResponse` is kept in schemas (used internally/tests) but no longer
  returned by any endpoint.

**What's next:**
- Add `GET /preferences` and `PATCH /preferences` endpoints (User.preferences JSONB)
- Google Cloud project setup to test live OAuth + GCal end-to-end
- Consider adding `GET /views/{id}/execute` as an alias for `GET /views/{id}/tasks`
  (frontend docs reference both names)

**Issues/blockers discovered:**
- None

### Session 2026-03-29 — OpenAPI docs review

**What was done:**
- Added `_DESCRIPTION` (markdown) and `_OPENAPI_TAGS` to `kairos/main.py`:
  - App description covers auth methods, auto-scheduling behaviour, and GCal fail-open semantics
  - Tag descriptions for all 7 groups (auth, tasks, projects, tags, views, schedule, blackout-days)
  - Added `contact` metadata to `FastAPI()` constructor
- Added informative docstrings to every endpoint across all 7 route files:
  - `tasks.py` — 7 endpoints: auto-schedule on write, soft-delete, unschedule/complete semantics
  - `projects.py` — 6 endpoints: soft-delete no-cascade note, flat-structure note
  - `tags.py` — 4 endpoints: 409-on-dup, hard-delete + cascade associations
  - `views.py` — 6 endpoints: view execution model explained
  - `blackout_days.py` — 3 endpoints: 409-on-dup, added `description=` to `Query` params
  - `auth.py` — 4 endpoints: OAuth scopes, no-auth note on public endpoints, key replacement
  - `schedule.py` — 4 endpoints: dry-run flag, GCal fail-open on free-slots, days clamping

**What changed:**
- No behaviour changed — documentation only, all 175 tests pass

**Decisions made:**
- `/schedule/free-slots` query param is `days` (integer horizon), not `start`/`end` as the
  original contract specified. This divergence is noted. The implementation is simpler and
  consistent with the scheduler's horizon model. Contract will need updating if a frontend requires explicit date ranges.

**What's next:**
- Google Cloud project setup to test live OAuth + GCal integration end-to-end
- Update `references/api-contract.md` to reflect the `days` param on `/schedule/free-slots`
- Consider adding an `openapi_extra` security scheme declaration (HTTPBearer + API key)

**Issues/blockers discovered:**
- None

### Session 2026-03-29 — Blackout days

**What was done:**
- Implemented `kairos/services/blackout_service.py` — `create_blackout_day`,
  `list_blackout_days` (with optional `date_from`/`date_to` filters), `delete_blackout_day`.
  Duplicate date raises `ValueError` (caught from `IntegrityError` on the unique constraint).
- Replaced stub routes in `kairos/api/blackout_days.py` — all 3 endpoints wired with
  auth + DB deps and proper response models. `POST` maps `ValueError` → 409.
  `DELETE` returns 404 on missing record.
- Replaced 3 stub tests in `tests/test_blackout_days.py` with 11 real tests:
  - `test_create_blackout_day`
  - `test_create_blackout_day_without_reason`
  - `test_create_duplicate_blackout_returns_409`
  - `test_list_blackout_days_empty`
  - `test_list_blackout_days`
  - `test_list_blackout_days_date_from_filter`
  - `test_list_blackout_days_date_to_filter`
  - `test_delete_blackout_day`
  - `test_delete_nonexistent_blackout_day_returns_404`
  - `test_blackout_days_require_auth`
  - `test_scheduler_skips_blackout_day`

**What changed:**
- `kairos/services/blackout_service.py` — implemented from single-line stub
- `kairos/api/blackout_days.py` — replaced stub routes with real implementations
- `tests/test_blackout_days.py` — replaced 3 stub tests with 11 real tests (175 total)

**Decisions made:**
- `create_blackout_day` catches `IntegrityError` from the DB unique constraint
  and re-raises as `ValueError` so the route layer handles it as HTTP 409.
- `delete_blackout_day` returns a boolean rather than raising, consistent with
  delete patterns used elsewhere (projects, tags, views).

**What's next:**
- Review OpenAPI docs (`/docs`) — verify all endpoint descriptions and response schemas
- Test live GCal integration once Google Cloud credentials are available

**Issues/blockers discovered:**
- None

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