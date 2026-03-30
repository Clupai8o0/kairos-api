from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kairos.api.router import api_router
from kairos.core.config import settings
from kairos.core.database import engine

_DESCRIPTION = """
Kairos is an AI-native scheduling and task management API.

Tasks go in, the engine decides when they happen, Google Calendar reflects reality.

## Authentication

All endpoints (except `/auth/google/login` and `/auth/google/callback`) require one of:
- **Bearer JWT** — obtained via the Google OAuth flow (`Authorization: Bearer <token>`)
- **API key** — obtained via `POST /auth/api-key` (`Authorization: Bearer kairos_sk_…`)

## Auto-scheduling

Creating or updating a task with `schedulable=true` and a `duration_mins` value
automatically triggers the scheduler. It reads your Google Calendar free/busy slots
and places the task in the next available window before its deadline.

## Google Calendar

GCal is the time source of truth. The DB stores a `gcal_event_id` reference.
If GCal is unreachable, task creation still succeeds — `scheduled_at` is left null
and a retry can be triggered via `POST /schedule/run`.
"""

_OPENAPI_TAGS = [
    {
        "name": "auth",
        "description": (
            "Google OAuth 2.0 flow and API key management. "
            "Use the OAuth flow to obtain a JWT, or generate an API key for "
            "agent / automation access."
        ),
    },
    {
        "name": "tasks",
        "description": (
            "Create and manage tasks. Auto-scheduling is triggered on create/update "
            "when `schedulable=true` and `duration_mins` is set."
        ),
    },
    {
        "name": "projects",
        "description": (
            "Flat project containers. Projects hold tasks — no nested hierarchy, "
            "no sprints, no phases."
        ),
    },
    {
        "name": "tags",
        "description": (
            "Universal tagging system. Tags replace categories, contexts, and areas. "
            "Name by convention: `area:work`, `context:laptop`, `type:deep-work`."
        ),
    },
    {
        "name": "views",
        "description": (
            "Saved filter + sort configurations. Create a view once, execute it to get "
            "a live filtered task list."
        ),
    },
    {
        "name": "schedule",
        "description": (
            "Trigger scheduling runs, inspect today's or this week's agenda, "
            "and query free time slots."
        ),
    },
    {
        "name": "calendar",
        "description": (
            "Connected Google accounts and calendar event APIs. "
            "Supports event detail fetch and in-app updates with optimistic concurrency."
        ),
    },
    {
        "name": "blackout-days",
        "description": (
            "Mark entire days as unavailable. The scheduler skips blackout days "
            "when placing tasks."
        ),
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Kairos",
        description=_DESCRIPTION,
        version="0.1.0",
        openapi_tags=_OPENAPI_TAGS,
        contact={"name": "Sam", "url": "https://kairos.clupai.com"},
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api/v1")

    return app


app = create_app()
