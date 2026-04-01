"""Tests for the scheduling engine — algorithm correctness, not API surface."""

from datetime import date, datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.task import Task, TaskStatus
from kairos.models.user import User
from kairos.services.gcal_service import BusySlot
from kairos.services.scheduler import (
    TimeSlot,
    calculate_urgency,
    can_schedule,
    find_best_slot,
    get_free_slots,
    run_scheduler,
    split_task,
)
from tests.mocks import MockGCalService


# ── Helpers ───────────────────────────────────────────────────────────────────

def utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_task(**kwargs) -> Task:
    defaults = dict(
        id="task_1",
        user_id="user_1",
        title="Test task",
        duration_mins=60,
        priority=3,
        status=TaskStatus.PENDING,
        schedulable=True,
        buffer_mins=15,
        is_splittable=False,
        min_chunk_mins=None,
        depends_on=[],
        created_at=utc(2026, 1, 1),
        deadline=None,
    )
    defaults.update(kwargs)
    return Task(**defaults)


# ── calculate_urgency ─────────────────────────────────────────────────────────

def test_urgency_priority_1_higher_than_priority_3() -> None:
    now = utc(2026, 4, 1)
    p1 = make_task(priority=1)
    p3 = make_task(priority=3)
    assert calculate_urgency(p1, now) > calculate_urgency(p3, now)


def test_urgency_overdue_task_gets_max_boost() -> None:
    now = utc(2026, 4, 2)
    overdue = make_task(deadline=utc(2026, 4, 1))  # already passed
    no_deadline = make_task()
    assert calculate_urgency(overdue, now) > calculate_urgency(no_deadline, now)


def test_urgency_deadline_within_24h_gets_high_boost() -> None:
    now = utc(2026, 4, 1, 8, 0)
    urgent = make_task(deadline=utc(2026, 4, 1, 20, 0))  # 12h away
    week_away = make_task(deadline=utc(2026, 4, 8))
    assert calculate_urgency(urgent, now) > calculate_urgency(week_away, now)


def test_urgency_short_task_gets_small_bonus() -> None:
    now = utc(2026, 4, 1)
    short = make_task(duration_mins=25)
    long_ = make_task(duration_mins=120)
    # Both same priority & no deadline — short task should score slightly higher
    assert calculate_urgency(short, now) > calculate_urgency(long_, now)


# ── get_free_slots ────────────────────────────────────────────────────────────

def test_free_slots_no_busy_returns_full_work_day() -> None:
    slots = get_free_slots(
        [],
        date(2026, 4, 1),
        time(9, 0),
        time(17, 0),
    )
    assert len(slots) == 1
    assert slots[0].duration_mins == 480.0


def test_free_slots_busy_at_start() -> None:
    busy = [BusySlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 10, 0))]
    slots = get_free_slots(busy, date(2026, 4, 1), time(9, 0), time(17, 0))
    assert len(slots) == 1
    assert slots[0].start == utc(2026, 4, 1, 10, 0)


def test_free_slots_busy_in_middle_splits_into_two() -> None:
    busy = [BusySlot(start=utc(2026, 4, 1, 11, 0), end=utc(2026, 4, 1, 12, 0))]
    slots = get_free_slots(busy, date(2026, 4, 1), time(9, 0), time(17, 0))
    assert len(slots) == 2
    assert slots[0].end == utc(2026, 4, 1, 11, 0)
    assert slots[1].start == utc(2026, 4, 1, 12, 0)


def test_free_slots_fully_busy_returns_nothing() -> None:
    busy = [BusySlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 17, 0))]
    slots = get_free_slots(busy, date(2026, 4, 1), time(9, 0), time(17, 0))
    assert slots == []


def test_free_slots_drops_slivers_under_5_min() -> None:
    # Leave only a 3-minute gap — should be dropped
    busy = [
        BusySlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 11, 57)),
        BusySlot(start=utc(2026, 4, 1, 12, 0), end=utc(2026, 4, 1, 17, 0)),
    ]
    slots = get_free_slots(busy, date(2026, 4, 1), time(9, 0), time(17, 0))
    assert all(s.duration_mins >= 5 for s in slots)


# ── find_best_slot ────────────────────────────────────────────────────────────

def test_find_best_slot_picks_first_fitting_slot() -> None:
    free = [
        TimeSlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 17, 0)),
    ]
    task = make_task(duration_mins=60, buffer_mins=15)
    slot = find_best_slot(task, free)
    assert slot is not None
    assert slot.start == utc(2026, 4, 1, 9, 0)
    assert slot.end == utc(2026, 4, 1, 10, 0)


def test_find_best_slot_returns_none_when_no_slot_fits() -> None:
    free = [TimeSlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 9, 30))]
    task = make_task(duration_mins=60, buffer_mins=15)
    assert find_best_slot(task, free) is None


def test_find_best_slot_respects_deadline() -> None:
    free = [TimeSlot(start=utc(2026, 4, 1, 14, 0), end=utc(2026, 4, 1, 17, 0))]
    task = make_task(
        duration_mins=60,
        buffer_mins=0,
        deadline=utc(2026, 4, 1, 14, 30),  # must start before 13:30
    )
    # Slot starts at 14:00 but deadline means latest start is 13:30 — no slot
    assert find_best_slot(task, free) is None


def test_find_best_slot_requires_duration_plus_buffer() -> None:
    # 70-minute slot, 60-min task + 15-min buffer = 75 min needed → won't fit
    free = [TimeSlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 10, 10))]
    task = make_task(duration_mins=60, buffer_mins=15)
    assert find_best_slot(task, free) is None


def test_find_best_slot_no_duration_returns_none() -> None:
    free = [TimeSlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 17, 0))]
    task = make_task(duration_mins=None)
    assert find_best_slot(task, free) is None


# ── split_task ────────────────────────────────────────────────────────────────

def test_split_task_across_two_slots() -> None:
    free = [
        TimeSlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 10, 30)),
        TimeSlot(start=utc(2026, 4, 1, 14, 0), end=utc(2026, 4, 1, 15, 30)),
    ]
    task = make_task(duration_mins=120, buffer_mins=0, min_chunk_mins=30, is_splittable=True)
    chunks = split_task(task, free)
    assert chunks is not None
    total = sum((c.end - c.start).total_seconds() / 60 for c in chunks)
    assert total == 120.0


def test_split_task_returns_none_when_not_enough_slots() -> None:
    free = [TimeSlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 9, 20))]
    task = make_task(duration_mins=120, buffer_mins=0, min_chunk_mins=30, is_splittable=True)
    assert split_task(task, free) is None


def test_split_task_returns_none_when_no_min_chunk_uses_default_30():
    """When min_chunk_mins is None, split_task defaults to 30-minute chunks."""
    free = [TimeSlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 17, 0))]
    task = make_task(duration_mins=120, buffer_mins=0, min_chunk_mins=None, is_splittable=True)
    chunks = split_task(task, free)
    assert chunks is not None
    total = sum((c.end - c.start).total_seconds() / 60 for c in chunks)
    assert total == 120.0


def test_split_task_default_chunk_respects_30_min_minimum():
    """With min_chunk_mins=None and only 20-min slots available, splitting fails."""
    free = [TimeSlot(start=utc(2026, 4, 1, 9, 0), end=utc(2026, 4, 1, 9, 20))]
    task = make_task(duration_mins=120, buffer_mins=0, min_chunk_mins=None, is_splittable=True)
    assert split_task(task, free) is None


# ── can_schedule ──────────────────────────────────────────────────────────────

def test_can_schedule_no_deps_returns_true() -> None:
    task = make_task(depends_on=[])
    assert can_schedule(task, {}) is True


def test_can_schedule_met_dependency_returns_true() -> None:
    dep = make_task(id="dep_1", status=TaskStatus.DONE)
    task = make_task(depends_on=["dep_1"])
    assert can_schedule(task, {"dep_1": dep}) is True


def test_can_schedule_unmet_dependency_returns_false() -> None:
    dep = make_task(id="dep_1", status=TaskStatus.PENDING)
    task = make_task(depends_on=["dep_1"])
    assert can_schedule(task, {"dep_1": dep}) is False


def test_can_schedule_missing_dependency_returns_false() -> None:
    task = make_task(depends_on=["ghost_task"])
    assert can_schedule(task, {}) is False


# ── run_scheduler (integration) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_scheduler_schedules_pending_task(
    db_session: AsyncSession, test_user: User
) -> None:
    gcal = MockGCalService()
    task = Task(
        id="sched_task_1",
        user_id=test_user.id,
        title="Write report",
        duration_mins=60,
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

    result = await run_scheduler(db_session, gcal, test_user)

    assert result.scheduled == 1
    assert result.failed == 0
    assert len(gcal.events) == 1
    await db_session.refresh(task)
    assert task.status == TaskStatus.SCHEDULED
    assert task.scheduled_at is not None
    assert task.gcal_event_id is not None


@pytest.mark.asyncio
async def test_run_scheduler_skips_task_without_duration(
    db_session: AsyncSession, test_user: User
) -> None:
    gcal = MockGCalService()
    task = Task(
        id="no_dur_task",
        user_id=test_user.id,
        title="Vague task",
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

    result = await run_scheduler(db_session, gcal, test_user)

    assert result.skipped == 1
    assert result.scheduled == 0
    assert len(gcal.events) == 0


@pytest.mark.asyncio
async def test_run_scheduler_skips_task_with_unmet_dependency(
    db_session: AsyncSession, test_user: User
) -> None:
    gcal = MockGCalService()
    blocker = Task(
        id="blocker_task",
        user_id=test_user.id,
        title="Blocker",
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
    dependent = Task(
        id="dependent_task",
        user_id=test_user.id,
        title="Depends on blocker",
        duration_mins=30,
        priority=3,
        status=TaskStatus.PENDING,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=["blocker_task"],
        created_at=utc(2026, 1, 1),
        metadata_json={},
    )
    db_session.add_all([blocker, dependent])
    await db_session.commit()

    result = await run_scheduler(db_session, gcal, test_user, task_ids=["dependent_task"])

    assert result.skipped == 1
    assert result.scheduled == 0


@pytest.mark.asyncio
async def test_run_scheduler_fails_when_calendar_fully_busy(
    db_session: AsyncSession, test_user: User
) -> None:
    gcal = MockGCalService()
    now = datetime.now(timezone.utc)
    # Block the entire scheduling horizon from now through 60 days out
    gcal.add_busy_slot(
        start=now - timedelta(hours=1),
        end=now + timedelta(days=60),
    )
    task = Task(
        id="stuck_task",
        user_id=test_user.id,
        title="No room",
        duration_mins=60,
        priority=1,
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

    result = await run_scheduler(db_session, gcal, test_user)

    assert result.failed == 1
    assert result.scheduled == 0


@pytest.mark.asyncio
async def test_run_scheduler_specific_task_ids_only(
    db_session: AsyncSession, test_user: User
) -> None:
    gcal = MockGCalService()
    task_a = Task(
        id="task_a",
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
        id="task_b",
        user_id=test_user.id,
        title="Task B",
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
    db_session.add_all([task_a, task_b])
    await db_session.commit()

    result = await run_scheduler(db_session, gcal, test_user, task_ids=["task_a"])

    assert result.scheduled == 1
    assert len(gcal.events) == 1


@pytest.mark.asyncio
async def test_run_scheduler_higher_priority_scheduled_first(
    db_session: AsyncSession, test_user: User
) -> None:
    """P1 task should be scheduled into the first (best) slot."""
    gcal = MockGCalService()
    low_p = Task(
        id="low_task",
        user_id=test_user.id,
        title="Low priority",
        duration_mins=60,
        priority=4,
        status=TaskStatus.PENDING,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=utc(2026, 1, 1),
        metadata_json={},
    )
    high_p = Task(
        id="high_task",
        user_id=test_user.id,
        title="High priority",
        duration_mins=60,
        priority=1,
        status=TaskStatus.PENDING,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=utc(2026, 1, 2),
        metadata_json={},
    )
    db_session.add_all([low_p, high_p])
    await db_session.commit()

    result = await run_scheduler(db_session, gcal, test_user)

    assert result.scheduled == 2
    await db_session.refresh(high_p)
    await db_session.refresh(low_p)
    # High priority task should be scheduled before (earlier time than) low priority
    assert high_p.scheduled_at <= low_p.scheduled_at


@pytest.mark.asyncio
async def test_run_scheduler_reschedule_does_not_drift_slot(
    db_session: AsyncSession, test_user: User
) -> None:
    """Regression: running the scheduler twice must not push a task forward.

    When a task is already scheduled at 9-10am, the free/busy query returns
    that window as busy (it's the existing GCal event). The scheduler must
    restore that window before finding a new slot — otherwise the task drifts
    to 10am on run 2 and back to 9am on run 3.
    """
    gcal = MockGCalService()
    now = datetime.now(timezone.utc)

    # Simulate a task already scheduled at tomorrow 9-10am UTC
    tomorrow = (now + timedelta(days=1)).date()
    sched_start = datetime.combine(tomorrow, time(9, 0), tzinfo=timezone.utc)
    sched_end = datetime.combine(tomorrow, time(10, 0), tzinfo=timezone.utc)

    existing_event_id = "existing_evt_0"
    # Pre-populate the mock as if GCal already has this event
    gcal.events[existing_event_id] = {
        "summary": "Already scheduled",
        "start": sched_start,
        "end": sched_end,
    }
    # free/busy returns the existing event's window as busy (real GCal behaviour)
    gcal.add_busy_slot(start=sched_start, end=sched_end)

    task = Task(
        id="drift_task",
        user_id=test_user.id,
        title="Already scheduled",
        duration_mins=60,
        priority=3,
        status=TaskStatus.SCHEDULED,
        schedulable=True,
        buffer_mins=0,
        is_splittable=False,
        depends_on=[],
        created_at=utc(2026, 1, 1),
        gcal_event_id=existing_event_id,
        scheduled_at=sched_start,
        scheduled_end=sched_end,
        metadata_json={},
    )
    db_session.add(task)
    await db_session.commit()

    result = await run_scheduler(db_session, gcal, test_user)

    assert result.scheduled == 1
    await db_session.refresh(task)
    # Must land back at the same 9am start, not drift later
    assert task.scheduled_at is not None
    assert task.scheduled_at.hour == 9
    assert task.scheduled_at.minute == 0
