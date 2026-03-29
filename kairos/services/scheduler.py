"""The scheduling engine. Core algorithm for slot-fitting tasks into Google Calendar."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.blackout_day import BlackoutDay
from kairos.models.schedule_log import ScheduleLog
from kairos.models.task import Task, TaskStatus
from kairos.models.user import User
from kairos.services.gcal_service import BusySlot, GCalService

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class TimeSlot:
    start: datetime
    end: datetime

    @property
    def duration_mins(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass
class ScheduleResult:
    scheduled: int = 0
    failed: int = 0
    skipped: int = 0
    details: list[dict] = field(default_factory=list)


# ── Urgency scoring ────────────────────────────────────────────────────────────

def calculate_urgency(task: Task, now: datetime) -> float:
    """Higher score → scheduled first → gets the best time slots."""
    score = 0.0

    priority_weights = {1: 100, 2: 60, 3: 30, 4: 10}
    score += priority_weights.get(task.priority, 30)

    if task.deadline:
        hours_until_deadline = (task.deadline - now).total_seconds() / 3600
        if hours_until_deadline <= 0:
            score += 200
        elif hours_until_deadline <= 24:
            score += 150
        elif hours_until_deadline <= 72:
            score += 80
        elif hours_until_deadline <= 168:
            score += 40
        else:
            score += 10

    if task.duration_mins and task.duration_mins <= 30:
        score += 5

    return score


def _sort_key(task: Task, now: datetime):
    return (
        -calculate_urgency(task, now),
        task.deadline or datetime.max.replace(tzinfo=timezone.utc),
        task.created_at,
        task.title,
    )


# ── Free-slot computation ──────────────────────────────────────────────────────

def get_free_slots(
    busy_slots: list[BusySlot],
    day: date,
    work_start: time,
    work_end: time,
) -> list[TimeSlot]:
    """Return free time blocks within work hours on a given day."""
    tz = timezone.utc  # All datetimes kept UTC; caller localises for display

    day_start = datetime.combine(day, work_start, tzinfo=tz)
    day_end = datetime.combine(day, work_end, tzinfo=tz)

    free: list[TimeSlot] = [TimeSlot(start=day_start, end=day_end)]

    for busy in sorted(busy_slots, key=lambda b: b.start):
        new_free: list[TimeSlot] = []
        for slot in free:
            # No overlap
            if busy.end <= slot.start or busy.start >= slot.end:
                new_free.append(slot)
                continue
            # Left fragment
            if busy.start > slot.start:
                new_free.append(TimeSlot(start=slot.start, end=busy.start))
            # Right fragment
            if busy.end < slot.end:
                new_free.append(TimeSlot(start=busy.end, end=slot.end))
        free = new_free

    # Drop slivers < 5 minutes
    return [s for s in free if s.duration_mins >= 5]


def find_best_slot(
    task: Task,
    free_slots: list[TimeSlot],
) -> TimeSlot | None:
    """Pick earliest slot that fits task duration + buffer, respecting deadline."""
    if not task.duration_mins:
        return None

    required_mins = task.duration_mins + task.buffer_mins

    for slot in free_slots:  # already sorted by start time
        if task.deadline:
            latest_start = task.deadline - timedelta(minutes=task.duration_mins)
            if slot.start > latest_start:
                return None  # All remaining slots are after deadline

        if slot.duration_mins >= required_mins:
            return TimeSlot(
                start=slot.start,
                end=slot.start + timedelta(minutes=task.duration_mins),
            )

    return None


def split_task(
    task: Task,
    free_slots: list[TimeSlot],
) -> list[TimeSlot] | None:
    """Split a splittable task across multiple free slots. Returns chunks or None."""
    if not task.duration_mins or not task.min_chunk_mins:
        return None

    remaining_mins = task.duration_mins
    chunks: list[TimeSlot] = []

    for slot in free_slots:
        if remaining_mins <= 0:
            break

        available = min(slot.duration_mins - task.buffer_mins, remaining_mins)
        if available >= task.min_chunk_mins:
            chunks.append(
                TimeSlot(
                    start=slot.start,
                    end=slot.start + timedelta(minutes=available),
                )
            )
            remaining_mins -= available

    if remaining_mins > 0:
        return None  # Couldn't fit all chunks

    return chunks


# ── Dependency check ───────────────────────────────────────────────────────────

def can_schedule(task: Task, all_tasks: dict[str, Task]) -> bool:
    """Return False if any dependency is unfinished."""
    for dep_id in (task.depends_on or []):
        dep = all_tasks.get(dep_id)
        if not dep or dep.status != TaskStatus.DONE:
            return False
    return True


# ── DB helpers ─────────────────────────────────────────────────────────────────

async def _get_blackout_dates(
    db: AsyncSession,
    user_id: str,
    start: date,
    end: date,
) -> set[date]:
    result = await db.execute(
        select(BlackoutDay.date).where(
            BlackoutDay.user_id == user_id,
            BlackoutDay.date >= start,
            BlackoutDay.date <= end,
        )
    )
    return {row[0] for row in result.all()}


async def _log(
    db: AsyncSession,
    user_id: str,
    task_id: str | None,
    action: str,
    details: dict,
) -> None:
    db.add(
        ScheduleLog(
            user_id=user_id,
            task_id=task_id,
            action=action,
            details=details,
        )
    )


# ── Main scheduler ─────────────────────────────────────────────────────────────

async def run_scheduler(
    db: AsyncSession,
    gcal: GCalService,
    user: User,
    task_ids: list[str] | None = None,
) -> ScheduleResult:
    """
    Schedule pending tasks into Google Calendar.

    If task_ids is provided, only those tasks are considered.
    Otherwise, all schedulable pending tasks for the user are processed.
    """
    result = ScheduleResult()
    now = datetime.now(timezone.utc)

    # ── 1. Collect tasks ───────────────────────────────────────────────────────
    query = select(Task).where(
        Task.user_id == user.id,
        Task.schedulable == True,  # noqa: E712
        Task.status.in_([TaskStatus.PENDING, TaskStatus.SCHEDULED]),
    )
    if task_ids:
        query = query.where(Task.id.in_(task_ids))

    rows = await db.execute(query)
    tasks: list[Task] = list(rows.scalars().all())

    if not tasks:
        return result

    # Build lookup for dependency checks
    all_tasks_map: dict[str, Task] = {t.id: t for t in tasks}

    # ── 2. Sort by urgency ─────────────────────────────────────────────────────
    tasks.sort(key=lambda t: _sort_key(t, now))

    # ── 3. Determine scheduling horizon ───────────────────────────────────────
    horizon_days: int = user.preferences.get("scheduling_horizon_days", 14)
    horizon_end = now + timedelta(days=horizon_days)

    # ── 4. Fetch free/busy from GCal ──────────────────────────────────────────
    try:
        busy_slots = await gcal.get_free_busy(user, now, horizon_end)
    except Exception as exc:
        logger.warning("GCal free/busy fetch failed: %s", exc)
        # Fail open — mark all as skipped rather than crashing
        for task in tasks:
            result.skipped += 1
            result.details.append({"task_id": task.id, "status": "skipped", "reason": "gcal_unavailable"})
        return result

    # ── 5. Fetch blackout days ─────────────────────────────────────────────────
    blackout_dates = await _get_blackout_dates(db, user.id, now.date(), horizon_end.date())

    # ── 6. Parse work hours ────────────────────────────────────────────────────
    wh = user.preferences.get("work_hours", {"start": "09:00", "end": "17:00"})
    work_start = time.fromisoformat(wh["start"])
    work_end = time.fromisoformat(wh["end"])

    # ── 7. Build day-indexed free slots ───────────────────────────────────────
    # Collect all free slots across the horizon, filtered to work hours and blackout days
    all_free_slots: list[TimeSlot] = []
    current = now.date()
    while current <= horizon_end.date():
        if current not in blackout_dates and current.weekday() < 5:
            day_slots = get_free_slots(busy_slots, current, work_start, work_end)
            # Clip to future (don't schedule in the past within today)
            clipped = [
                TimeSlot(start=max(s.start, now), end=s.end)
                for s in day_slots
                if s.end > now
            ]
            all_free_slots.extend(s for s in clipped if s.duration_mins >= 5)
        current += timedelta(days=1)

    # ── 8. Schedule each task ──────────────────────────────────────────────────
    for task in tasks:
        if not task.duration_mins:
            result.skipped += 1
            result.details.append({"task_id": task.id, "status": "skipped", "reason": "no_duration"})
            continue

        if not can_schedule(task, all_tasks_map):
            result.skipped += 1
            result.details.append({"task_id": task.id, "status": "skipped", "reason": "unmet_dependencies"})
            continue

        # Try to slot the task (with conflict retry)
        scheduled = False
        for attempt in range(3):
            slot = find_best_slot(task, all_free_slots)

            if slot is None and task.is_splittable and task.min_chunk_mins:
                chunks = split_task(task, all_free_slots)
                if chunks:
                    scheduled = await _schedule_split_task(
                        db, gcal, user, task, chunks, all_free_slots, result
                    )
                    break

            if slot is None:
                result.failed += 1
                result.details.append({"task_id": task.id, "status": "failed", "reason": "no_slot_available"})
                break

            # Write to GCal
            try:
                event_id = await gcal.create_event(
                    user=user,
                    summary=task.title,
                    start=slot.start,
                    end=slot.end,
                    description=f"Kairos task: {task.id}",
                    task_id=task.id,
                )
            except Exception as exc:
                logger.warning("GCal create_event failed (attempt %d): %s", attempt + 1, exc)
                if attempt < 2:
                    # Refresh free/busy and retry
                    try:
                        busy_slots = await gcal.get_free_busy(user, now, horizon_end)
                        all_free_slots = _recompute_free_slots(
                            busy_slots, now, horizon_end, blackout_dates, work_start, work_end
                        )
                    except Exception:
                        pass
                    continue
                result.failed += 1
                result.details.append({"task_id": task.id, "status": "failed", "reason": str(exc)})
                break

            # Persist to DB
            task.gcal_event_id = event_id
            task.scheduled_at = slot.start
            task.scheduled_end = slot.end
            task.status = TaskStatus.SCHEDULED

            await _log(db, user.id, task.id, "scheduled", {
                "event_id": event_id,
                "start": slot.start.isoformat(),
                "end": slot.end.isoformat(),
            })

            # Consume the used slot from free slots
            _consume_slot(all_free_slots, slot, task.buffer_mins)

            result.scheduled += 1
            result.details.append({"task_id": task.id, "status": "scheduled", "event_id": event_id})
            scheduled = True
            break

    await db.flush()
    return result


async def _schedule_split_task(
    db: AsyncSession,
    gcal: GCalService,
    user: User,
    task: Task,
    chunks: list[TimeSlot],
    all_free_slots: list[TimeSlot],
    result: ScheduleResult,
) -> bool:
    """Create multiple GCal events for a splittable task. Returns True on success."""
    event_ids: list[str] = []
    total = len(chunks)

    for i, chunk in enumerate(chunks, start=1):
        label = f"{task.title} ({i}/{total})"
        try:
            event_id = await gcal.create_event(
                user=user,
                summary=label,
                start=chunk.start,
                end=chunk.end,
                description=f"Kairos task: {task.id}",
                task_id=task.id,
            )
        except Exception as exc:
            # Roll back already-created chunks
            for eid in event_ids:
                try:
                    await gcal.delete_event(user, eid)
                except Exception:
                    pass
            result.failed += 1
            result.details.append({"task_id": task.id, "status": "failed", "reason": str(exc)})
            return False

        event_ids.append(event_id)
        _consume_slot(all_free_slots, chunk, task.buffer_mins)

    task.gcal_event_id = json.dumps(event_ids)
    task.scheduled_at = chunks[0].start
    task.scheduled_end = chunks[-1].end
    task.status = TaskStatus.SCHEDULED

    await _log(db, user.id, task.id, "scheduled_split", {
        "event_ids": event_ids,
        "chunks": [{"start": c.start.isoformat(), "end": c.end.isoformat()} for c in chunks],
    })

    result.scheduled += 1
    result.details.append({"task_id": task.id, "status": "scheduled", "event_ids": event_ids})
    return True


def _consume_slot(
    free_slots: list[TimeSlot],
    used: TimeSlot,
    buffer_mins: int,
) -> None:
    """Remove a used time + buffer from the free slots list (in-place)."""
    # Extend used window by buffer
    used_end = used.end + timedelta(minutes=buffer_mins)
    new_free: list[TimeSlot] = []
    for slot in free_slots:
        if used_end <= slot.start or used.start >= slot.end:
            new_free.append(slot)
            continue
        if used.start > slot.start:
            new_free.append(TimeSlot(start=slot.start, end=used.start))
        if used_end < slot.end:
            new_free.append(TimeSlot(start=used_end, end=slot.end))
    free_slots[:] = [s for s in new_free if s.duration_mins >= 5]


def _recompute_free_slots(
    busy: list[BusySlot],
    now: datetime,
    horizon_end: datetime,
    blackout_dates: set[date],
    work_start: time,
    work_end: time,
) -> list[TimeSlot]:
    """Recompute all free slots from scratch (used on conflict retry)."""
    all_free: list[TimeSlot] = []
    current = now.date()
    while current <= horizon_end.date():
        if current not in blackout_dates and current.weekday() < 5:
            day_slots = get_free_slots(busy, current, work_start, work_end)
            clipped = [
                TimeSlot(start=max(s.start, now), end=s.end)
                for s in day_slots
                if s.end > now
            ]
            all_free.extend(s for s in clipped if s.duration_mins >= 5)
        current += timedelta(days=1)
    return all_free
