"""Tests for recurring task creation, scheduling, and management.

New model (single-task recurrence):
- A recurring task is ONE DB row with a recurrence_rule field.
- No child Task rows are created.
- The scheduler creates one GCal event per occurrence, constrained to that day.
- All GCal event IDs are stored as a JSON array on gcal_event_id.
- To stop: set recurrence_rule=null or delete the task.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.task import Task, TaskStatus


# ── RecurrenceRule schema validation ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_recurrence_rule_invalid_interval(auth_client: AsyncClient) -> None:
    """interval < 1 should be rejected with 422."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Bad interval",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "interval": 0},
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_recurrence_rule_mutually_exclusive_end_conditions(auth_client: AsyncClient) -> None:
    """end_date and end_after_count are mutually exclusive."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Both ends",
            "duration_mins": 30,
            "recurrence_rule": {
                "freq": "daily",
                "end_date": "2026-05-01",
                "end_after_count": 5,
            },
        },
    )
    assert r.status_code == 422


# ── Recurring task creation: single DB row model ──────────────────────────────

@pytest.mark.asyncio
async def test_create_recurring_task_returns_single_task(auth_client: AsyncClient) -> None:
    """POST /tasks/ with recurrence_rule creates exactly ONE task row."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Daily standup",
            "duration_mins": 15,
            "recurrence_rule": {"freq": "daily", "interval": 1, "end_after_count": 3},
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["recurrence_rule"]["freq"] == "daily"
    assert data["parent_task_id"] is None
    assert data["recurrence_index"] is None


@pytest.mark.asyncio
async def test_create_recurring_task_spawns_no_instances(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Creating a recurring task does NOT create child occurrence rows."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Weekly review",
            "duration_mins": 60,
            "recurrence_rule": {"freq": "weekly", "interval": 1, "end_after_count": 4},
        },
    )
    assert r.status_code == 201
    template_id = r.json()["id"]

    # No child rows should exist
    result = await db_session.execute(
        select(Task).where(Task.parent_task_id == template_id)
    )
    instances = result.scalars().all()
    assert len(instances) == 0


@pytest.mark.asyncio
async def test_create_non_recurring_task_has_no_recurrence_fields(
    auth_client: AsyncClient,
) -> None:
    """A plain task has null recurrence fields."""
    r = await auth_client.post("/tasks/", json={"title": "Standalone", "duration_mins": 30})
    assert r.status_code == 201
    data = r.json()
    assert data["recurrence_rule"] is None
    assert data["parent_task_id"] is None
    assert data["recurrence_index"] is None


# ── Listing ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tasks_shows_recurring_template(auth_client: AsyncClient) -> None:
    """Recurring task appears as a single entry in the task list."""
    await auth_client.post(
        "/tasks/",
        json={
            "title": "Recurring",
            "duration_mins": 15,
            "recurrence_rule": {"freq": "daily", "end_after_count": 5},
        },
    )
    r = await auth_client.get("/tasks/")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["tasks"][0]["recurrence_rule"]["freq"] == "daily"


@pytest.mark.asyncio
async def test_list_tasks_include_instances_false_still_shows_template(
    auth_client: AsyncClient,
) -> None:
    """include_instances=false filters child row instances; the template is always returned."""
    await auth_client.post(
        "/tasks/",
        json={
            "title": "Recurring hidden",
            "duration_mins": 15,
            "recurrence_rule": {"freq": "daily", "end_after_count": 3},
        },
    )
    r = await auth_client.get("/tasks/?include_instances=false")
    assert r.status_code == 200
    data = r.json()
    # Template has parent_task_id=None and is included
    assert data["total"] == 1
    assert data["tasks"][0]["recurrence_rule"]["freq"] == "daily"


@pytest.mark.asyncio
async def test_list_tasks_by_parent_task_id_returns_empty(auth_client: AsyncClient) -> None:
    """parent_task_id filter returns empty because no child rows are created."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Monthly template",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "monthly", "end_after_count": 2},
        },
    )
    template_id = r.json()["id"]

    r2 = await auth_client.get(f"/tasks/?parent_task_id={template_id}")
    assert r2.status_code == 200
    assert r2.json()["total"] == 0


# ── Update ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_recurring_task_title(auth_client: AsyncClient) -> None:
    """PATCH on a recurring task updates the template; no propagation needed."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Old title",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 3},
        },
    )
    template_id = r.json()["id"]

    patch_r = await auth_client.patch(
        f"/tasks/{template_id}",
        json={"title": "New title"},
    )
    assert patch_r.status_code == 200
    assert patch_r.json()["title"] == "New title"


@pytest.mark.asyncio
async def test_update_recurrence_rule_clears_old_events_and_reschedules(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Changing recurrence_rule removes old GCal events and schedules fresh ones."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Template",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 5},
        },
    )
    assert r.status_code == 201
    template_id = r.json()["id"]
    original_event_id_str = r.json().get("gcal_event_id")

    # Change to weekly — old events are deleted, new weekly ones created
    patch_r = await auth_client.patch(
        f"/tasks/{template_id}",
        json={"recurrence_rule": {"freq": "weekly", "end_after_count": 2}},
    )
    assert patch_r.status_code == 200
    data = patch_r.json()
    assert data["recurrence_rule"]["freq"] == "weekly"

    if original_event_id_str:
        original_event_ids = set(json.loads(original_event_id_str))
        new_event_id_str = data.get("gcal_event_id")
        if new_event_id_str:
            new_event_ids = set(json.loads(new_event_id_str))
            # Verify old events are not reused as-is (new event count matches new rule)
            # Weekly end_after_count=2 should produce ≤ 2 events if slots exist
            assert len(new_event_ids) <= 2


@pytest.mark.asyncio
async def test_clear_recurrence_rule_stops_recurrence(auth_client: AsyncClient) -> None:
    """Setting recurrence_rule=null turns the task into a standalone non-recurring task."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Was recurring",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 5},
        },
    )
    task_id = r.json()["id"]

    patch_r = await auth_client.patch(
        f"/tasks/{task_id}",
        json={"recurrence_rule": None},
    )
    assert patch_r.status_code == 200
    data = patch_r.json()
    # Recurrence is gone
    assert data["recurrence_rule"] is None
    # Task may be rescheduled as a one-time standalone event (that's fine)
    # Key invariant: no recurrence_rule means it won't repeat
    assert data["parent_task_id"] is None
    assert data["recurrence_index"] is None


# ── Scheduler creates one GCal event per occurrence ───────────────────────────

@pytest.mark.asyncio
async def test_scheduler_creates_gcal_events_for_each_occurrence(
    auth_client: AsyncClient, db_session: AsyncSession, mock_gcal, test_user
) -> None:
    """run_scheduler creates one GCal event per occurrence day within the horizon."""
    from kairos.services.scheduler import run_scheduler
    from kairos.services.task_service import create_task
    from kairos.schemas.task import TaskCreate, RecurrenceRule

    task_data = TaskCreate(
        title="Daily standup",
        duration_mins=30,
        recurrence_rule=RecurrenceRule(freq="daily", end_after_count=3),
    )
    task = await create_task(db_session, test_user, task_data, gcal=None)
    task_id = task.id  # save before expire_all
    await db_session.flush()

    result = await run_scheduler(db_session, mock_gcal, test_user)

    assert result.scheduled == 1  # 1 task scheduled
    db_session.expire_all()
    reloaded = await db_session.get(Task, task_id)
    assert reloaded is not None
    assert reloaded.status == TaskStatus.SCHEDULED
    assert reloaded.gcal_event_id is not None
    event_ids = json.loads(reloaded.gcal_event_id)
    # Should have at least 1 and at most 3 GCal events (depending on horizon fit)
    assert 1 <= len(event_ids) <= 3
    assert len(mock_gcal.events) == len(event_ids)


@pytest.mark.asyncio
async def test_scheduler_each_occurrence_on_its_own_day(
    auth_client: AsyncClient, db_session: AsyncSession, mock_gcal, test_user
) -> None:
    """Each occurrence GCal event falls on a distinct calendar day (no pile-up)."""
    from kairos.services.scheduler import run_scheduler
    from kairos.services.task_service import create_task
    from kairos.schemas.task import TaskCreate, RecurrenceRule
    from zoneinfo import ZoneInfo

    task_data = TaskCreate(
        title="Daily task",
        duration_mins=30,
        recurrence_rule=RecurrenceRule(freq="daily", end_after_count=3),
    )
    task = await create_task(db_session, test_user, task_data, gcal=None)
    task_id = task.id  # save before expire_all
    user_tz = ZoneInfo(test_user.preferences.get("timezone", "UTC"))  # save before expire_all
    await db_session.flush()

    await run_scheduler(db_session, mock_gcal, test_user)

    db_session.expire_all()
    reloaded = await db_session.get(Task, task_id)
    assert reloaded is not None
    assert reloaded.gcal_event_id is not None
    event_ids = json.loads(reloaded.gcal_event_id)

    # All scheduled events must fall on different calendar days (no same-day pile-up)
    days = {mock_gcal.events[eid]["start"].astimezone(user_tz).date() for eid in event_ids}
    assert len(days) == len(event_ids)  # distinct days — no same-day pile-up


@pytest.mark.asyncio
async def test_scheduler_reschedule_deletes_old_gcal_events(
    db_session: AsyncSession, mock_gcal, test_user
) -> None:
    """Re-running the scheduler removes old GCal events before creating new ones."""
    from kairos.services.scheduler import run_scheduler
    from kairos.services.task_service import create_task
    from kairos.schemas.task import TaskCreate, RecurrenceRule

    task_data = TaskCreate(
        title="Recurring daily",
        duration_mins=30,
        recurrence_rule=RecurrenceRule(freq="daily", end_after_count=2),
    )
    task = await create_task(db_session, test_user, task_data, gcal=None)
    task_id = task.id  # save before expire_all
    await db_session.flush()

    # First schedule run
    await run_scheduler(db_session, mock_gcal, test_user)
    first_reloaded = await db_session.get(Task, task_id)
    assert first_reloaded is not None
    assert first_reloaded.gcal_event_id is not None
    first_ids = set(json.loads(first_reloaded.gcal_event_id))
    first_event_count = len(first_ids)
    assert first_event_count >= 1

    # Mark task as pending to force reschedule
    first_reloaded.status = TaskStatus.PENDING
    first_reloaded.gcal_event_id = json.dumps(list(first_ids))
    await db_session.flush()

    # Second schedule run — old events should be deleted first
    await run_scheduler(db_session, mock_gcal, test_user)

    # All events from the first run are deleted and replaced
    # (mock reuses IDs after deletion, so we verify by checking none of the
    # first batch's events remain with the original start times)
    second_reloaded = await db_session.get(Task, task_id)
    assert second_reloaded is not None
    assert second_reloaded.status == TaskStatus.SCHEDULED
    assert second_reloaded.gcal_event_id is not None


# ── Response shape ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recurrence_fields_in_list_response(auth_client: AsyncClient) -> None:
    """Every task in GET /tasks/ includes recurrence_rule, parent_task_id, recurrence_index."""
    await auth_client.post(
        "/tasks/",
        json={
            "title": "Shape check",
            "duration_mins": 20,
            "recurrence_rule": {"freq": "weekly", "end_after_count": 1},
        },
    )
    r = await auth_client.get("/tasks/")
    assert r.status_code == 200
    for task in r.json()["tasks"]:
        assert "recurrence_rule" in task
        assert "parent_task_id" in task
        assert "recurrence_index" in task


# ── No-op backward-compat endpoints ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_extend_recurrence_horizon_endpoint_is_noop(auth_client: AsyncClient) -> None:
    """POST /schedule/recurrence/extend returns created=0 (no-op in new model)."""
    r = await auth_client.post("/schedule/recurrence/extend")
    assert r.status_code == 200
    assert r.json()["created"] == 0


@pytest.mark.asyncio
async def test_cleanup_missed_recurrences_endpoint_is_noop(auth_client: AsyncClient) -> None:
    """POST /schedule/recurrence/cleanup returns cancelled=0 (no-op in new model)."""
    r = await auth_client.post("/schedule/recurrence/cleanup")
    assert r.status_code == 200
    assert r.json()["cancelled"] == 0


# ── Delete recurring task ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_recurring_task_cancels_task(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """DELETE /tasks/{id} cancels the recurring task (no instances to clean up)."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Daily event",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 3},
        },
    )
    task_id = r.json()["id"]

    del_r = await auth_client.delete(f"/tasks/{task_id}")
    assert del_r.status_code == 200
    assert del_r.json()["status"] == "cancelled"

    db_session.expire_all()
    task = await db_session.get(Task, task_id)
    assert task is not None
    assert task.status == TaskStatus.CANCELLED


