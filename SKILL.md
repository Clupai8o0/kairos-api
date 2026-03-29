---
name: kairos-backend
description: >
  Guide for building and extending Kairos — Sam's AI-native scheduling and task management API.
  Use this skill whenever the user mentions Kairos, auto-scheduling, task/event creation,
  the Clupai ecosystem, FlowSavvy clone, or any backend work related to the scheduling app.
  Also trigger when the user asks about the Kairos data model, scheduling engine,
  Google Calendar integration, or OpenClaw API integration. Trigger aggressively —
  if the task involves scheduling, task management, or the Kairos codebase, use this skill.
---

# Kairos Backend — Claude Development Guide

## What Is Kairos

Kairos is a solo-built AI-native scheduling and productivity API. It is the core backend
for the Clupai ecosystem (`kairos.clupai.com`). Its purpose is to eliminate scheduling
decisions — tasks go in, the engine decides when they happen, Google Calendar reflects reality.

**This is infrastructure, not a toy.** OpenClaw, future agents, and the frontend all consume
this single API. Every design decision must account for that.

## Read Order

**On every session, always read these two files first — in this order:**

1. **`CHANGELOG.md`** — Session memory. Current project state, what's been built, what's
   next, active decisions, known issues. This is Claude's memory across sessions.
2. **`references/architecture-decisions.md`** — Non-negotiable constraints and resolved decisions.

If `CHANGELOG.md` and an ADR conflict, `CHANGELOG.md` wins (it's newer — decisions evolve
during development). If `CHANGELOG.md` records a decision that should be permanent, move it
to `architecture-decisions.md` as a new ADR.

Then read the relevant reference file for the current task:

| Working on...                  | Read this first                                      |
|-------------------------------|------------------------------------------------------|
| Data models / schema          | `references/data-model.md`                           |
| Scheduling engine logic       | `references/scheduling-engine.md`                    |
| API endpoints / routes        | `references/api-contract.md`                         |
| Project structure / setup     | `references/project-structure.md`                    |
| Google Calendar integration   | `references/gcal-integration.md`                     |
| Writing or updating tests     | `references/testing.md`                              |

### File Maintenance Rules

These docs files live in the repo root or a `docs/` directory. Claude maintains them:

| File | Lives at | Claude's responsibility |
|------|----------|------------------------|
| `README.md` | Repo root | Update when setup steps change, new dependencies are added, or project structure changes. This is the public-facing project doc. |
| `CHANGELOG.md` | Repo root or `docs/` | Update every session (mandatory — see Session Checklist). |
| `docs/references/*.md` | `docs/references/` | Update when the relevant system changes (e.g., new model fields → update `data-model.md`). |
| `docs/SKILL.md` | `docs/` | Rarely changes. Only update if core principles, stack, or module boundaries change. |

**README.md is the project's front door.** If a dependency is added, a setup step changes,
a new command is needed, or the project structure shifts — update the README in the same
session. Don't leave it stale.

---

## Stack

| Layer           | Choice                        | Reason                                              |
|----------------|-------------------------------|-----------------------------------------------------|
| Language        | Python 3.12+                  | Meta cert alignment, AI ecosystem, fastest to ship  |
| Framework       | FastAPI                       | Async-native, auto OpenAPI docs, type validation    |
| ORM             | SQLAlchemy 2.0 (async)        | Mature, flexible, async support                     |
| Migrations      | Alembic                       | Standard for SQLAlchemy, version-controlled schema   |
| Database        | PostgreSQL 16                 | Relational, JSONB for flexible metadata, proven      |
| Auth            | Google OAuth 2.0              | Single auth flow, GCal permissions bundled           |
| Calendar        | Google Calendar API v3        | Source of truth for time blocks                      |
| Task Queue      | None (v1) → Celery (v2)      | Background scheduling jobs when needed               |
| Validation      | Pydantic v2                   | Built into FastAPI, strict typing                    |
| Testing         | pytest + httpx                | Async test client for FastAPI                        |
| Containerisation| Docker + docker-compose       | Local dev parity, future deployment                  |

---

## Core Principles

1. **Google Calendar is the time source of truth.** Your DB stores tasks/projects. GCal stores when things happen. Never duplicate calendar state in the DB beyond a reference ID.

2. **One API, many consumers.** The API must be callable by: the frontend, OpenClaw agents, n8n workflows, CLI scripts, and future integrations. Every endpoint must work with just an API key or OAuth token — no frontend-specific assumptions.

3. **Flat project structure.** No phases. Projects contain tasks. Tasks have dependencies (optional) and tags. That's it. Complexity comes from the scheduling engine, not the data model.

4. **Tags are the universal organiser.** Views, filters, grouping, and reporting all operate on tags. Tags replace categories, contexts, areas, and types. One system, infinite flexibility.

5. **Schedule-on-write by default.** When a task is created or updated, the scheduler evaluates whether to reschedule. The caller doesn't need to think about it.

6. **Fail open, log everything.** If GCal is unreachable, the task is still created in the DB with `scheduled_at = null`. A background retry picks it up. Never block task creation on external service availability.

---

## Module Boundaries

The backend is one FastAPI application with clean internal modules:

```
kairos/
├── api/              # Route handlers (thin — delegate to services)
│   ├── tasks.py
│   ├── projects.py
│   ├── schedule.py
│   ├── tags.py
│   ├── views.py
│   └── auth.py
├── services/         # Business logic
│   ├── task_service.py
│   ├── project_service.py
│   ├── scheduler.py          # The scheduling engine
│   ├── gcal_service.py       # Google Calendar read/write
│   └── tag_service.py
├── models/           # SQLAlchemy models
│   ├── task.py
│   ├── project.py
│   ├── tag.py
│   ├── view.py
│   └── user.py
├── schemas/          # Pydantic request/response schemas
├── core/             # Config, auth, deps, middleware
│   ├── config.py
│   ├── auth.py
│   ├── database.py
│   └── deps.py
├── migrations/       # Alembic migrations
└── tests/
```

**Rule:** Routes call services. Services call models and external APIs. Models never import from services. No circular dependencies.

---

## Development Workflow

1. **Always run migrations before writing new model code.** Check `alembic heads` to confirm you're on the latest.
2. **Write the Pydantic schema first**, then the model, then the service, then the route. Outside-in.
3. **Every endpoint gets a test.** Use `httpx.AsyncClient` with FastAPI's test client.
4. **Use `KAIROS_ENV=test` for test runs** — this uses an in-memory SQLite or test PostgreSQL instance.
5. **Docker-compose for local dev.** `docker-compose up` should give you: API + PostgreSQL + (later) Redis.

---

## What NOT to Build (v1)

- No frontend. Backend only. Frontend is a separate project.
- No AI chat layer. That's a future module — the API is the foundation.
- No voice input/output. That's frontend + a thin API wrapper later.
- No recurring task engine. Manual recurrence (duplicate task) is fine for v1.
- No multi-user. Single user (Sam) with Google OAuth. Multi-user is a v2 concern.
- No WebSocket/real-time. REST only. Polling is fine for v1.

---

## V1 Scope — FlowSavvy Clone Feature Parity

The v1 milestone is: **create tasks, auto-schedule them into Google Calendar free slots.**

Specifically:
1. CRUD for tasks (with tags, duration, deadline, priority, project association)
2. CRUD for projects (flat container of tasks)
3. Tag system (create, assign, filter)
4. Scheduling engine: read GCal free/busy → slot tasks by priority/deadline → write events back
5. View system: saved filters (e.g. "Work tasks due this week", "All high-priority unscheduled")
6. Google OAuth + GCal read/write integration
7. OpenAPI docs auto-generated

**Done means:** you can POST a task, hit POST /schedule/run, and see it appear in your Google Calendar in the right free slot.

---

## Session Checklist (for Claude)

### Session Start (every session, no exceptions)

- [ ] Read `CHANGELOG.md` — understand current state, what's built, what's next, active decisions
- [ ] Read `references/architecture-decisions.md` — confirm constraints haven't been forgotten
- [ ] Check which module the user wants to work on
- [ ] Read the relevant reference file(s) from the Read Order table
- [ ] If the codebase exists, verify actual file state matches CHANGELOG (don't trust memory)

### During Session

- [ ] Write code that follows the module boundaries above
- [ ] Include type hints on every function
- [ ] Write or update tests for any new endpoint or service function — read `references/testing.md`
  for the exact test cases required for the module being built
- [ ] If a design decision is made mid-session, note it immediately in the Active Decisions
  section of `CHANGELOG.md` — don't wait until session end

### Session End (every session, no exceptions)

- [ ] Append a session log entry to `CHANGELOG.md` using the template in that file
- [ ] Update the "Current State" checklist (tick off completed items)
- [ ] Update "Known issues" and "Blocked on" if anything changed
- [ ] If a mid-session decision should be permanent, add it to `architecture-decisions.md` as a new ADR
- [ ] If setup steps, dependencies, or project structure changed, update `README.md`
- [ ] If a model, endpoint, or engine rule changed, update the relevant `references/*.md` file
- [ ] State the next concrete action for the following session