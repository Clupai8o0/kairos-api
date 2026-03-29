# Kairos Testing Guide

Every feature ships with tests. No exceptions. This doc defines the testing standards,
patterns, and specific test cases required for each module.

---

## Table of Contents
1. [Testing Stack](#testing-stack)
2. [Test Structure](#test-structure)
3. [Fixtures & Setup](#fixtures--setup)
4. [Writing Tests](#writing-tests)
5. [Per-Feature Test Specs](#per-feature-test-specs)
   - [Auth](#auth)
   - [Tasks](#tasks)
   - [Projects](#projects)
   - [Tags](#tags)
   - [Views](#views)
   - [Scheduling Engine](#scheduling-engine)
   - [Google Calendar Service](#google-calendar-service)
   - [Blackout Days](#blackout-days)
   - [Schedule Endpoints](#schedule-endpoints)
6. [Running Tests](#running-tests)

---

## Testing Stack

| Tool | Purpose |
|------|---------|
| pytest | Test runner |
| pytest-asyncio | Async test support |
| httpx | Async test client for FastAPI |
| factory_boy (optional) | Test data factories |

---

## Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures (db, client, mock services, factories)
├── test_auth.py
├── test_tasks.py
├── test_projects.py
├── test_tags.py
├── test_views.py
├── test_scheduler.py        # Most critical — the core algorithm
├── test_gcal_service.py
├── test_blackout_days.py
└── test_schedule_endpoints.py
```

---

## Fixtures & Setup

### conftest.py — Core Fixtures

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from kairos.main import create_app
from kairos.core.database import Base
from kairos.core.deps import get_db, get_gcal_service
from kairos.models import User

# Use SQLite for tests (fast, no Docker needed for CI)
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"


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
    """Create a default test user."""
    user = User(
        id="test_user_1",
        email="sam@test.com",
        name="Sam",
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
    return user


@pytest_asyncio.fixture
async def mock_gcal():
    """Mock Google Calendar service — no real API calls."""
    from tests.mocks import MockGCalService
    return MockGCalService()


@pytest_asyncio.fixture
async def client(db_session, mock_gcal, test_user):
    """Async test client with dependency overrides."""
    app = create_app()

    async def override_db():
        yield db_session

    async def override_gcal():
        return mock_gcal

    async def override_auth():
        return test_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_gcal_service] = override_gcal
    # Override auth to skip OAuth — always return test_user
    from kairos.core.deps import get_current_user
    app.dependency_overrides[get_current_user] = override_auth

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test/api/v1",
    ) as c:
        yield c
```

### Mock GCal Service

```python
# tests/mocks.py

from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class MockGCalService:
    events: dict[str, dict] = field(default_factory=dict)
    busy_slots: list[dict] = field(default_factory=list)

    async def get_free_busy(self, user, time_min, time_max, **kwargs):
        return [s for s in self.busy_slots if s["end"] > time_min and s["start"] < time_max]

    async def create_event(self, user, summary, start, end, **kwargs):
        event_id = f"mock_evt_{len(self.events)}"
        self.events[event_id] = {"summary": summary, "start": start, "end": end}
        return event_id

    async def update_event(self, user, event_id, **kwargs):
        if event_id in self.events:
            self.events[event_id].update({k: v for k, v in kwargs.items() if v is not None})

    async def delete_event(self, user, event_id, **kwargs):
        self.events.pop(event_id, None)

    async def get_events(self, user, time_min, time_max, **kwargs):
        return [
            {**e, "id": eid}
            for eid, e in self.events.items()
            if e["end"] > time_min and e["start"] < time_max
        ]

    def add_busy_slot(self, start: datetime, end: datetime):
        """Test helper — simulate existing calendar events."""
        self.busy_slots.append({"start": start, "end": end})
```

---

## Writing Tests

### Rules

1. **One test file per module.** `test_tasks.py` tests task endpoints, not scheduler logic.
2. **Test the API surface, not internals.** Hit endpoints via `client`, not service functions directly. Exception: `test_scheduler.py` tests the scheduling algorithm directly since it's complex internal logic.
3. **Each test is independent.** No test depends on another test's side effects. Use fixtures for setup.
4. **Name tests descriptively.** `test_create_task_without_duration_stays_pending` not `test_task_1`.
5. **Test both happy path and error cases.** Every endpoint needs at least one success test and one validation/error test.
6. **Assert status codes AND response body.** Don't just check 200 — verify the returned data is correct.

### Pattern

```python
@pytest.mark.asyncio
async def test_create_task_with_all_fields(client):
    response = await client.post("/tasks", json={
        "title": "Review PR",
        "duration_mins": 30,
        "priority": 2,
        "deadline": "2026-04-01T17:00:00Z",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Review PR"
    assert data["duration_mins"] == 30
    assert data["status"] == "pending"  # or "scheduled" if auto-schedule worked
```

---

## Per-Feature Test Specs

### Auth

**File:** `test_auth.py`

| Test | What it verifies |
|------|-----------------|
| `test_google_oauth_redirect` | `GET /auth/google` returns 302 redirect to Google |
| `test_google_callback_creates_user` | Callback with valid code creates user + returns JWT |
| `test_google_callback_existing_user` | Callback for existing email updates tokens, doesn't duplicate |
| `test_api_key_generation` | `POST /auth/api-key` returns a valid key |
| `test_api_key_authenticates` | Request with valid API key in header passes auth |
| `test_invalid_token_returns_401` | Request with bad/expired JWT returns 401 |
| `test_missing_auth_returns_401` | Request with no auth header returns 401 |

---

### Tasks

**File:** `test_tasks.py`

**CRUD — Happy Path:**

| Test | What it verifies |
|------|-----------------|
| `test_create_task_minimal` | POST with only `title` → 201, defaults applied |
| `test_create_task_all_fields` | POST with every field → 201, all fields stored correctly |
| `test_list_tasks_empty` | GET when no tasks → 200, empty list |
| `test_list_tasks_returns_all` | GET after creating 3 tasks → 200, 3 tasks returned |
| `test_get_task_by_id` | GET /:id → 200, correct task returned |
| `test_update_task_partial` | PATCH with one field → 200, only that field changed |
| `test_update_task_multiple_fields` | PATCH with multiple fields → all updated |
| `test_delete_task_soft` | DELETE → 200, status becomes "cancelled" |
| `test_complete_task` | POST /:id/complete → status "done", completed_at set |
| `test_unschedule_task` | POST /:id/unschedule → status "pending", scheduled_at cleared |

**CRUD — Error Cases:**

| Test | What it verifies |
|------|-----------------|
| `test_create_task_no_title_returns_422` | POST without title → 422 validation error |
| `test_get_nonexistent_task_returns_404` | GET with fake ID → 404 |
| `test_update_nonexistent_task_returns_404` | PATCH with fake ID → 404 |
| `test_delete_nonexistent_task_returns_404` | DELETE with fake ID → 404 |
| `test_create_task_invalid_priority_returns_422` | Priority outside 1-4 → 422 |
| `test_create_task_negative_duration_returns_422` | Negative duration_mins → 422 |

**Filtering:**

| Test | What it verifies |
|------|-----------------|
| `test_filter_tasks_by_status` | `?status=pending` returns only pending tasks |
| `test_filter_tasks_by_priority` | `?priority=1,2` returns only P1 and P2 |
| `test_filter_tasks_by_project` | `?project_id=xxx` returns only that project's tasks |
| `test_filter_tasks_by_tag` | `?tag_ids=xxx` returns only tagged tasks |
| `test_filter_tasks_by_scheduled` | `?is_scheduled=false` returns unscheduled only |
| `test_filter_tasks_by_deadline` | `?due_before=date` returns tasks due before that date |
| `test_filter_tasks_combined` | Multiple filters applied together (AND logic) |
| `test_search_tasks_by_keyword` | `?search=review` matches title/description |
| `test_sort_tasks_by_priority` | `?sort=priority&order=asc` returns correct order |
| `test_pagination_limit_offset` | `?limit=2&offset=2` returns correct page |

**Tags on Tasks:**

| Test | What it verifies |
|------|-----------------|
| `test_create_task_with_tags` | POST with `tag_ids` → task has those tags |
| `test_update_task_tags` | PATCH with new `tag_ids` → replaces tag associations |
| `test_task_response_includes_tags` | GET returns tags array with id, name, color |

**Dependencies:**

| Test | What it verifies |
|------|-----------------|
| `test_create_task_with_depends_on` | POST with `depends_on: [id]` → stored correctly |
| `test_depends_on_nonexistent_task` | POST with fake dep ID → still creates (soft reference) |

---

### Projects

**File:** `test_projects.py`

| Test | What it verifies |
|------|-----------------|
| `test_create_project` | POST → 201 with all fields |
| `test_list_projects` | GET returns all active projects |
| `test_get_project_with_tasks` | GET /:id includes task summary list |
| `test_update_project` | PATCH → updated fields |
| `test_archive_project` | DELETE → status "archived", tasks NOT deleted |
| `test_filter_projects_by_status` | `?status=active` filters correctly |
| `test_get_project_tasks_with_filters` | GET /:id/tasks respects filter params |
| `test_create_project_with_tags` | POST with `tag_ids` → associated correctly |

---

### Tags

**File:** `test_tags.py`

| Test | What it verifies |
|------|-----------------|
| `test_create_tag` | POST → 201 with name, color, icon |
| `test_create_duplicate_tag_returns_409` | Same name for same user → 409 conflict |
| `test_list_tags_with_counts` | GET returns tags with task_count and project_count |
| `test_update_tag` | PATCH name/color → updated |
| `test_delete_tag_removes_associations` | DELETE → tag gone, task/project associations removed |
| `test_tag_name_validation` | Empty name or >100 chars → 422 |

---

### Views

**File:** `test_views.py`

| Test | What it verifies |
|------|-----------------|
| `test_create_view` | POST with filter_config → 201 |
| `test_list_views_ordered` | GET returns views sorted by position |
| `test_get_view` | GET /:id returns filter + sort config |
| `test_execute_view_returns_matching_tasks` | GET /:id/tasks applies filters correctly |
| `test_view_filter_tags_include` | `tags_include` returns only tasks with ALL listed tags |
| `test_view_filter_tags_exclude` | `tags_exclude` excludes tasks with ANY listed tag |
| `test_view_filter_status` | Filters by status array |
| `test_view_filter_priority` | Filters by priority array |
| `test_view_filter_due_within_days` | Relative deadline filter works |
| `test_view_filter_is_scheduled` | Boolean filter for scheduled/unscheduled |
| `test_view_filter_project_id` | Scopes to single project |
| `test_view_filter_search` | Keyword search on title + description |
| `test_view_sort_config` | Results respect sort field + direction |
| `test_update_view` | PATCH filter_config → new filters apply |
| `test_delete_view` | DELETE → 200, view gone |
| `test_default_views_exist` | New user has Today, This Week, Unscheduled, High Priority |

---

### Scheduling Engine

**File:** `test_scheduler.py`

This is the most important test file. Test the scheduling algorithm directly,
not through API endpoints. Import the service functions and call them.

**Urgency Scoring:**

| Test | What it verifies |
|------|-----------------|
| `test_urgency_p1_higher_than_p4` | Priority 1 task scores higher than priority 4 |
| `test_urgency_overdue_highest` | Past-deadline task gets highest urgency |
| `test_urgency_due_today_beats_due_next_week` | Deadline pressure increases score |
| `test_urgency_tiebreak_earlier_deadline_wins` | Same score → earlier deadline first |
| `test_urgency_tiebreak_earlier_created_wins` | Same score + same deadline → earlier created_at |

**Slot Finding:**

| Test | What it verifies |
|------|-----------------|
| `test_find_slot_empty_calendar` | Full work hours available → slots in first available morning |
| `test_find_slot_respects_work_hours` | Doesn't schedule outside 09:00-17:00 |
| `test_find_slot_avoids_busy_time` | Skips busy slots from GCal |
| `test_find_slot_includes_buffer` | 60min task + 15min buffer needs 75min slot |
| `test_find_slot_respects_deadline` | Won't schedule after deadline minus duration |
| `test_find_slot_earliest_fit` | Picks earliest valid slot, not largest |
| `test_find_slot_no_availability_returns_none` | Fully booked calendar → None |
| `test_find_slot_slot_too_small` | 30min gap for 60min task → skipped |

**Task Splitting:**

| Test | What it verifies |
|------|-----------------|
| `test_split_task_into_chunks` | 2hr task, min_chunk=30 → multiple blocks |
| `test_split_respects_min_chunk` | Won't create chunk smaller than min_chunk_mins |
| `test_split_total_equals_duration` | Sum of chunks = original duration_mins |
| `test_split_not_enough_slots` | Can't fit all chunks → returns None |
| `test_non_splittable_task_not_split` | is_splittable=False → never split |

**Dependencies:**

| Test | What it verifies |
|------|-----------------|
| `test_skip_task_with_unmet_dependency` | Dep not done → task skipped |
| `test_schedule_task_with_met_dependency` | Dep done → task scheduled normally |
| `test_skip_task_dep_cancelled` | Dep cancelled → task skipped with reason |

**Full Schedule Run:**

| Test | What it verifies |
|------|-----------------|
| `test_schedule_run_empty_backlog` | No pending tasks → nothing changes |
| `test_schedule_run_single_task` | One task → scheduled into first free slot |
| `test_schedule_run_multiple_tasks_by_priority` | Higher priority tasks get earlier slots |
| `test_schedule_run_respects_blackout_days` | Tasks not placed on blackout days |
| `test_schedule_run_skips_no_duration_tasks` | Tasks without duration stay pending |
| `test_schedule_run_creates_gcal_events` | Mock GCal has events after run |
| `test_schedule_run_dry_run` | dry_run=True → returns plan, no GCal writes |
| `test_schedule_run_idempotent` | Running twice without changes → same result |
| `test_reschedule_doesnt_move_well_placed_tasks` | Already-scheduled task stays if slot is still valid |

**Schedule-on-Write:**

| Test | What it verifies |
|------|-----------------|
| `test_create_task_triggers_scheduling` | POST /tasks with duration → scheduled_at populated |
| `test_create_task_no_duration_no_scheduling` | POST without duration → stays pending |
| `test_update_priority_triggers_reschedule` | PATCH priority → may get new slot |
| `test_update_deadline_triggers_reschedule` | PATCH deadline → may get new slot |
| `test_update_title_no_reschedule` | PATCH title → no scheduling side effect |

---

### Google Calendar Service

**File:** `test_gcal_service.py`

These test the GCal service wrapper in isolation using the mock.
Integration tests against real GCal are manual / separate.

| Test | What it verifies |
|------|-----------------|
| `test_get_free_busy_returns_busy_slots` | Mock returns correct busy periods |
| `test_get_free_busy_empty_calendar` | No busy slots → empty list |
| `test_create_event_returns_id` | Creates event, returns event ID |
| `test_delete_event_removes_it` | After delete, event not in mock store |
| `test_update_event_changes_fields` | Updated summary/time reflected |
| `test_get_events_in_range` | Only events within time range returned |
| `test_free_slot_calculation_basic` | Busy 10-11, work 9-17 → free 9-10, 11-17 |
| `test_free_slot_multiple_busy_blocks` | Multiple busy periods → correct gaps |
| `test_free_slot_busy_covers_all_work_hours` | No free time → empty list |
| `test_free_slot_respects_work_hours` | Busy at 7am (before work hours) → ignored |

---

### Blackout Days

**File:** `test_blackout_days.py`

| Test | What it verifies |
|------|-----------------|
| `test_create_blackout_day` | POST → 201 |
| `test_create_duplicate_blackout_returns_409` | Same date twice → conflict |
| `test_list_blackout_days` | GET returns all, supports date filters |
| `test_delete_blackout_day` | DELETE → removed |
| `test_scheduler_skips_blackout_day` | Task not placed on a blackout date |

---

### Schedule Endpoints

**File:** `test_schedule_endpoints.py`

| Test | What it verifies |
|------|-----------------|
| `test_schedule_run_returns_summary` | POST /schedule/run → scheduled + failed + unchanged counts |
| `test_schedule_run_specific_tasks` | POST with task_ids → only those tasks processed |
| `test_schedule_run_dry_run` | dry_run=True → no side effects |
| `test_schedule_today_returns_merged` | GET /schedule/today → tasks + GCal events merged by time |
| `test_schedule_today_empty` | No events today → empty items list |
| `test_schedule_week` | GET /schedule/week → 7 days of data |
| `test_free_slots_returns_available_time` | GET /schedule/free-slots → correct gaps |
| `test_free_slots_respects_min_duration` | min_duration_mins filters out small gaps |

---

## Running Tests

```bash
# Run all tests
pytest -v

# Run a specific test file
pytest tests/test_tasks.py -v

# Run a specific test
pytest tests/test_scheduler.py::test_schedule_run_single_task -v

# Run with coverage
pytest --cov=kairos --cov-report=term-missing

# Run only fast tests (skip integration)
pytest -m "not integration" -v

# Run in parallel (install pytest-xdist)
pytest -n auto -v
```

### Test Markers

```python
# Use markers to categorise tests
@pytest.mark.asyncio           # All async tests (required)
@pytest.mark.integration       # Tests that need real services
@pytest.mark.slow              # Tests that take >1s
```

Register markers in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests requiring external services",
    "slow: tests taking more than 1 second",
]
asyncio_mode = "auto"
```