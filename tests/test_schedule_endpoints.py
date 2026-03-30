"""Tests for schedule endpoints — POST /schedule/run, GET /schedule/today, etc."""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from kairos.models.task import Task, TaskStatus


def utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ── POST /schedule/run ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedule_run_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.post("/schedule/run")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_schedule_run_no_tasks_returns_zero_counts(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post("/schedule/run", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["scheduled"] == 0
    assert data["failed"] == 0
    assert data["skipped"] == 0


@pytest.mark.asyncio
async def test_schedule_run_schedules_pending_task(
    auth_client: AsyncClient,
    db_session,
    test_user,
) -> None:
    task = Task(
        id="endpoint_task_1",
        user_id=test_user.id,
        title="Book dentist",
        duration_mins=30,
        priority=2,
        status=TaskStatus.PENDING,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=utc(2026, 1, 1),
        metadata_json={},
    )
    db_session.add(task)
    await db_session.commit()

    response = await auth_client.post("/schedule/run", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["scheduled"] >= 1


@pytest.mark.asyncio
async def test_schedule_run_with_specific_task_ids(
    auth_client: AsyncClient,
    db_session,
    test_user,
) -> None:
    task_a = Task(
        id="ep_task_a",
        user_id=test_user.id,
        title="Task A",
        duration_mins=30,
        priority=3,
        status=TaskStatus.PENDING,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=utc(2026, 1, 1),
        metadata_json={},
    )
    task_b = Task(
        id="ep_task_b",
        user_id=test_user.id,
        title="Task B",
        duration_mins=30,
        priority=3,
        status=TaskStatus.PENDING,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=utc(2026, 1, 2),
        metadata_json={},
    )
    db_session.add_all([task_a, task_b])
    await db_session.commit()

    response = await auth_client.post("/schedule/run", json={"task_ids": ["ep_task_a"]})
    assert response.status_code == 200
    data = response.json()
    assert data["scheduled"] == 1


@pytest.mark.asyncio
async def test_schedule_run_skips_unschedulable_task(
    auth_client: AsyncClient,
    db_session,
    test_user,
) -> None:
    task = Task(
        id="unsched_task",
        user_id=test_user.id,
        title="No duration",
        duration_mins=None,
        priority=3,
        status=TaskStatus.PENDING,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=utc(2026, 1, 1),
        metadata_json={},
    )
    db_session.add(task)
    await db_session.commit()

    response = await auth_client.post("/schedule/run", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["skipped"] >= 1


# ── GET /schedule/today ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedule_today_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get("/schedule/today")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_schedule_today_empty_when_no_tasks(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/schedule/today")
    assert response.status_code == 200
    data = response.json()
    assert "date" in data
    assert data["items"] == []


@pytest.mark.asyncio
async def test_schedule_today_returns_todays_tasks(
    auth_client: AsyncClient,
    db_session,
    test_user,
) -> None:
    now = datetime.now(timezone.utc)
    task = Task(
        id="today_task",
        user_id=test_user.id,
        title="Today's task",
        duration_mins=60,
        priority=2,
        status=TaskStatus.SCHEDULED,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=utc(2026, 1, 1),
        metadata_json={},
        scheduled_at=now.replace(hour=10, minute=0, second=0, microsecond=0),
        scheduled_end=now.replace(hour=11, minute=0, second=0, microsecond=0),
        gcal_event_id="fake_gcal_id",
    )
    db_session.add(task)
    await db_session.commit()

    response = await auth_client.get("/schedule/today")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["type"] == "task"
    assert item["task"]["title"] == "Today's task"
    assert item["task"]["gcal_event_id"] == "fake_gcal_id"


@pytest.mark.asyncio
async def test_schedule_today_includes_google_event_contract(
    auth_client: AsyncClient,
    mock_gcal,
) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="primary",
        calendar_name="Primary",
        access_role="writer",
    )
    now = datetime.now(timezone.utc)
    await mock_gcal.create_event(
        user=None,
        summary="Team sync",
        start=now.replace(hour=9, minute=0, second=0, microsecond=0),
        end=now.replace(hour=9, minute=30, second=0, microsecond=0),
        account_id="acct_one",
        calendar_id="primary",
        calendar_name="Primary",
        description="Daily",
        location="Room 1",
        is_recurring_instance=True,
        recurring_event_id="recurring_1",
    )

    response = await auth_client.get("/schedule/today")
    assert response.status_code == 200
    items = response.json()["items"]
    event_item = next(item for item in items if item["type"] == "event")
    payload = event_item["gcal_event"]
    assert payload["provider"] == "google"
    assert payload["account_id"] == "acct_one"
    assert payload["calendar_id"] == "primary"
    assert payload["calendar_name"] == "Primary"
    assert payload["summary"] == "Team sync"
    assert payload["description"] == "Daily"
    assert payload["location"] == "Room 1"
    assert payload["is_recurring_instance"] is True
    assert payload["recurring_event_id"] == "recurring_1"
    assert payload["can_edit"] is True
    assert payload["etag"]


# ── GET /schedule/week ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedule_week_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get("/schedule/week")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_schedule_week_empty_when_no_tasks(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/schedule/week")
    assert response.status_code == 200
    assert response.json() == []  # No days with tasks → empty list


@pytest.mark.asyncio
async def test_schedule_week_merges_multiple_accounts(
    auth_client: AsyncClient,
    mock_gcal,
) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="cal_work",
        calendar_name="Work",
        access_role="writer",
    )
    mock_gcal.seed_calendar(
        account_id="acct_two",
        account_email="sam+two@test.com",
        calendar_id="cal_personal",
        calendar_name="Personal",
        access_role="writer",
    )

    monday = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    await mock_gcal.create_event(
        user=None,
        summary="Work block",
        start=monday,
        end=monday.replace(hour=9),
        account_id="acct_one",
        calendar_id="cal_work",
        calendar_name="Work",
    )
    await mock_gcal.create_event(
        user=None,
        summary="Gym",
        start=monday.replace(hour=18),
        end=monday.replace(hour=19),
        account_id="acct_two",
        calendar_id="cal_personal",
        calendar_name="Personal",
    )

    response = await auth_client.get("/schedule/week")
    assert response.status_code == 200
    events = [
        item["gcal_event"]["summary"]
        for day in response.json()
        for item in day["items"]
        if item["type"] == "event"
    ]
    assert "Work block" in events
    assert "Gym" in events


# ── GET /schedule/free-slots ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_free_slots_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get("/schedule/free-slots")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_free_slots_returns_slots_list(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/schedule/free-slots")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_free_slots_each_has_start_end_duration(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/schedule/free-slots")
    assert response.status_code == 200
    for slot in response.json():
        assert "start" in slot
        assert "end" in slot
        assert "duration_mins" in slot
        assert slot["duration_mins"] > 0
