# Architecture Decisions Record (ADR)

This file contains resolved architectural decisions for Kairos. These are final unless
explicitly overridden by Sam in conversation. Claude should not re-litigate these.

---

## ADR-001: FastAPI over Express/Django/Go

**Decision:** Python + FastAPI

**Context:** Sam is completing the Meta Back-End Developer Certificate (Python/Django).
FastAPI shares the Python ecosystem, Pydantic validation patterns, and async paradigms.
Express gives no credential compounding. Go adds a language learning tax. Django is
too opinionated for a scheduling API (admin panel, template engine — unnecessary weight).

**Consequences:**
- All backend code is Python 3.12+
- Type hints are mandatory (Pydantic + mypy compatible)
- Async endpoints by default (`async def`)
- SQLAlchemy 2.0 async session pattern

---

## ADR-002: PostgreSQL as the only database

**Decision:** PostgreSQL 16, no Redis/MongoDB/SQLite in production.

**Context:** The data model is relational (tasks belong to projects, tags are many-to-many).
PostgreSQL JSONB handles flexible metadata without a document store. For v1, there is no
caching layer — direct DB queries are fast enough for a single user.

**Consequences:**
- All data in one PostgreSQL instance
- JSONB columns for `metadata` and `preferences` fields
- No Redis until proven necessary (task queue, caching)
- SQLite allowed only in test environment

---

## ADR-003: Google Calendar is the time source of truth

**Decision:** Events exist in Google Calendar. The DB stores a `gcal_event_id` reference.

**Context:** Google Calendar handles recurring events, timezone math, invites, and
conflict detection. Rebuilding any of this is waste. The scheduler reads free/busy from
GCal, writes events back, and stores the event ID for reference.

**Consequences:**
- No `events` table in the DB — tasks get a `gcal_event_id` when scheduled
- `scheduled_at` in the tasks table is a denormalised cache of when GCal placed it
- If GCal is unreachable, task creation still succeeds (scheduled_at = null, retry later)
- Frontend reads merged data: tasks from API + events from GCal (via API proxy)

---

## ADR-004: Tags replace categories/contexts/areas/types

**Decision:** One universal tag system. No separate category, context, or area models.

**Context:** FlowSavvy uses categories. Todoist uses labels + projects. Notion uses
properties. All of these are just tags with different names. One system is simpler
to build, query, and extend.

**Consequences:**
- `Tag` model with: id, user_id, name, color, icon (optional)
- Many-to-many relationship: tasks ↔ tags, projects ↔ tags
- Views are saved tag-based filters
- Tag namespacing is by convention (e.g. "area:work", "context:laptop") not schema

---

## ADR-005: Flat project structure — no phases, no sprints

**Decision:** Projects are flat containers of tasks. No nested hierarchy.

**Context:** Sam explicitly prefers flat backlog with task dependencies over phased
project management. Kairos is not Jira. Tasks within a project can have optional
`depends_on` references, but there are no milestones, sprints, or phases.

**Consequences:**
- Project model has no `phases` or `milestones` relation
- Task model has optional `depends_on` (array of task IDs)
- Scheduling engine respects dependencies: dependent tasks scheduled after their prerequisites
- UI can group/sort tasks however it wants — the API just returns flat lists with metadata

---

## ADR-006: Schedule-on-write (auto-scheduling by default)

**Decision:** Creating or updating a task triggers a scheduling evaluation.

**Context:** The goal is to eliminate scheduling decisions. The user should never need to
manually decide when to do something. When a task is created with sufficient metadata
(duration, deadline, priority), the scheduler attempts to place it immediately.

**Consequences:**
- `POST /tasks` → create task → attempt schedule → return task with `scheduled_at`
- `PATCH /tasks/:id` (if duration/deadline/priority changed) → re-evaluate schedule
- `POST /schedule/run` still exists for manual full-reschedule
- Tasks without duration cannot be auto-scheduled (they stay in backlog)
- Scheduling failures are non-blocking — task is created with `scheduled_at = null`

---

## ADR-007: Single-user for v1

**Decision:** No multi-tenancy in v1. One user (Sam), one Google account.

**Context:** Building auth, permissions, team features, and data isolation before the
core scheduling engine works is premature. v1 is a personal tool.

**Consequences:**
- User model exists (for future expansion) but auth is simplified
- No team/org model
- No permission system beyond "is this user authenticated"
- API key auth for OpenClaw/agent access alongside OAuth for browser access

---

## ADR-008: API-first, no frontend coupling

**Decision:** The API returns JSON. It has no opinions about how data is displayed.

**Context:** The frontend is a separate project (likely Next.js at `kairos.clupai.com`).
OpenClaw, n8n, CLI scripts, and other agents also consume this API. No endpoint should
assume a browser client.

**Consequences:**
- No server-side rendering, no HTML responses
- No cookie-based sessions (use Bearer tokens)
- CORS configured for known origins (kairos.clupai.com, localhost:3000)
- OpenAPI schema auto-generated and always current
- All dates are ISO 8601 UTC. Frontend handles timezone display.

---

## ADR-009: View system for saved filters

**Decision:** Views are saved filter configurations, not materialised data.

**Context:** "Show me all high-priority work tasks due this week" is a view. It's a saved
query, not a separate data structure. This gives infinite flexibility without schema changes.

**Consequences:**
- `View` model stores: name, filter_config (JSONB), sort_config, user_id
- filter_config example: `{"tags": ["area:work"], "priority": [1], "due_before": "7d"}`
- API endpoint: `GET /views/:id/tasks` → applies filter, returns matching tasks
- Default views seeded on user creation (Today, This Week, Unscheduled, High Priority)

---

## ADR-010: Monolith with clean module boundaries

**Decision:** One FastAPI application. No microservices.

**Context:** Sam is a solo developer. Microservices add deployment complexity,
inter-service communication, distributed tracing, and debugging overhead — all for
zero benefit at this scale. Clean internal module boundaries (api/, services/, models/)
give the same code organisation without the operational cost.

**Consequences:**
- Single `uvicorn` process serves everything
- Docker-compose for local dev: one API container + one PostgreSQL container
- If a module grows too large, extract it later — not before
- No message queues, no service mesh, no API gateway in v1