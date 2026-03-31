"""Tests for schedule endpoints — POST /schedule/run, GET /schedule/today, etc."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
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
async def test_schedule_run_accepts_free_calendar_ids(
    auth_client: AsyncClient,
    db_session,
    test_user,
    mock_gcal,
) -> None:
    captured: dict[str, set[str] | None] = {}

    async def fake_get_free_busy(user, time_min, time_max, **kwargs):
        captured["calendar_ids"] = kwargs.get("calendar_ids")
        captured["free_calendar_ids"] = kwargs.get("free_calendar_ids")
        return []

    mock_gcal.get_free_busy = fake_get_free_busy  # type: ignore[method-assign]

    task = Task(
        id="ep_task_free_ids",
        user_id=test_user.id,
        title="Task with scoped calendars",
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
    db_session.add(task)
    await db_session.commit()

    response = await auth_client.post(
        "/schedule/run",
        json={
            "calendar_ids": ["work", "personal"],
            "free_calendar_ids": ["personal", "unknown"],
        },
    )
    assert response.status_code == 200
    assert captured["calendar_ids"] == {"work", "personal"}
    # Endpoint intersects free_calendar_ids with calendar_ids.
    assert captured["free_calendar_ids"] == {"personal"}


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
    base = utc(2026, 4, 1)
    start = utc(2026, 4, 1, 10, 0)
    end = utc(2026, 4, 1, 11, 0)
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
        scheduled_at=start,
        scheduled_end=end,
        gcal_event_id="fake_gcal_id",
    )
    db_session.add(task)
    await db_session.commit()

    local_day = base.astimezone(ZoneInfo("Australia/Melbourne")).date().isoformat()
    response = await auth_client.get(f"/schedule/today?day={local_day}")
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
    base = utc(2026, 4, 1)
    await mock_gcal.create_event(
        user=None,
        summary="Team sync",
        start=utc(2026, 4, 1, 9, 0),
        end=utc(2026, 4, 1, 9, 30),
        account_id="acct_one",
        calendar_id="primary",
        calendar_name="Primary",
        description="Daily",
        location="Room 1",
        is_recurring_instance=True,
        recurring_event_id="recurring_1",
    )

    local_day = base.astimezone(ZoneInfo("Australia/Melbourne")).date().isoformat()
    response = await auth_client.get(f"/schedule/today?day={local_day}")
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


@pytest.mark.asyncio
async def test_schedule_today_excludes_task_backed_events_by_default(
    auth_client: AsyncClient,
    db_session,
    test_user,
    mock_gcal,
) -> None:
    now = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)
    event_id = await mock_gcal.create_event(
        user=None,
        summary="Synced task",
        start=now,
        end=now.replace(hour=15),
        task_id="today_task_backed",
    )

    task = Task(
        id="today_task_backed",
        user_id=test_user.id,
        title="Synced task",
        duration_mins=60,
        priority=2,
        status=TaskStatus.SCHEDULED,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=utc(2026, 1, 1),
        metadata_json={},
        scheduled_at=now,
        scheduled_end=now.replace(hour=15),
        gcal_event_id=event_id,
    )
    db_session.add(task)
    await db_session.commit()

    local_day = now.astimezone(ZoneInfo("Australia/Melbourne")).date().isoformat()
    response = await auth_client.get(f"/schedule/today?day={local_day}")
    assert response.status_code == 200
    items = response.json()["items"]

    assert len([item for item in items if item["type"] == "task"]) == 1
    assert len([item for item in items if item["type"] == "event"]) == 0


@pytest.mark.asyncio
async def test_schedule_today_includes_and_flags_task_backed_events_with_option(
    auth_client: AsyncClient,
    mock_gcal,
) -> None:
    now = utc(2026, 4, 1, 9, 0)
    await mock_gcal.create_event(
        user=None,
        summary="Task-backed event",
        start=now,
        end=utc(2026, 4, 1, 10, 0),
        task_id="task_123",
    )

    local_day = now.astimezone(ZoneInfo("Australia/Melbourne")).date().isoformat()
    response = await auth_client.get(f"/schedule/today?day={local_day}&task_events=include")
    assert response.status_code == 200
    event_item = next(item for item in response.json()["items"] if item["type"] == "event")
    assert event_item["gcal_event"]["is_task_event"] is True
    assert event_item["gcal_event"]["task_id"] == "task_123"


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


@pytest.mark.asyncio
async def test_schedule_week_calendar_ids_filter_limits_event_sources(
    auth_client: AsyncClient,
    mock_gcal,
) -> None:
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="work",
        calendar_name="Work",
        access_role="writer",
    )
    mock_gcal.seed_calendar(
        account_id="acct_one",
        account_email="sam+one@test.com",
        calendar_id="personal",
        calendar_name="Personal",
        access_role="writer",
    )

    now = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    await mock_gcal.create_event(
        user=None,
        summary="Work event",
        start=now,
        end=now.replace(hour=9),
        account_id="acct_one",
        calendar_id="work",
        calendar_name="Work",
    )
    await mock_gcal.create_event(
        user=None,
        summary="Personal event",
        start=now.replace(hour=18),
        end=now.replace(hour=19),
        account_id="acct_one",
        calendar_id="personal",
        calendar_name="Personal",
    )

    response = await auth_client.get("/schedule/week?calendar_ids=work")
    assert response.status_code == 200
    events = [
        item["gcal_event"]["summary"]
        for day in response.json()
        for item in day["items"]
        if item["type"] == "event"
    ]
    assert "Work event" in events
    assert "Personal event" not in events


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
