"""The scheduling engine. Core algorithm for slot-fitting tasks into Google Calendar."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kairos.models.blackout_day import BlackoutDay
from kairos.models.schedule_log import ScheduleLog
from kairos.models.task import Task, TaskStatus
from kairos.models.user import User
from kairos.schemas.task import RecurrenceRule
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


# ── Timezone helpers ──────────────────────────────────────────────────────────

def _to_utc(dt: datetime) -> datetime:
    """Ensure a datetime is UTC-aware. TZ-naive datetimes are assumed to be UTC.

    SQLite strips timezone info when storing/retrieving datetimes; this prevents
    'can\'t subtract offset-naive and offset-aware datetimes' errors at runtime.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Urgency scoring ────────────────────────────────────────────────────────────

def calculate_urgency(task: Task, now: datetime) -> float:
    """Higher score → scheduled first → gets the best time slots."""
    score = 0.0

    priority_weights = {1: 100, 2: 60, 3: 30, 4: 10}
    score += priority_weights.get(task.priority, 30)

    if task.deadline:
        hours_until_deadline = (_to_utc(task.deadline) - now).total_seconds() / 3600
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
    deadline = _to_utc(task.deadline) if task.deadline else datetime.max.replace(tzinfo=timezone.utc)
    return (
        -calculate_urgency(task, now),
        deadline,
        task.created_at,
        task.title,
    )


# ── Free-slot computation ──────────────────────────────────────────────────────

def get_free_slots(
    busy_slots: list[BusySlot],
    day: date,
    work_start: time,
    work_end: time,
    tz: tzinfo = timezone.utc,
) -> list[TimeSlot]:
    """Return free time blocks within work hours on a given day."""
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
            latest_start = _to_utc(task.deadline) - timedelta(minutes=task.duration_mins)
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
    if not task.duration_mins:
        return None

    min_chunk = task.min_chunk_mins if task.min_chunk_mins is not None else 30

    remaining_mins = task.duration_mins
    chunks: list[TimeSlot] = []

    for slot in free_slots:
        if remaining_mins <= 0:
            break

        available = min(slot.duration_mins - task.buffer_mins, remaining_mins)
        if available >= min_chunk:
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


def _occurrence_dates(
    rule: RecurrenceRule,
    from_date: date,
    until: date,
    count_offset: int = 0,
) -> list[date]:
    """Return occurrence dates starting at from_date up to (not exceeding) until.

    count_offset: number of occurrences already generated (used for end_after_count enforcement).
    """
    results: list[date] = []
    current = from_date
    count = count_offset

    while current <= until:
        if rule.end_date and current > rule.end_date:
            break
        if rule.end_after_count is not None and count >= rule.end_after_count:
            break

        # For weekly with days_of_week, only include matching weekdays
        if rule.freq == "weekly" and rule.days_of_week:
            dow_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
            if current.weekday() in {dow_map[d] for d in rule.days_of_week if d in dow_map}:
                results.append(current)
                count += 1
            current += timedelta(days=1)
            continue

        results.append(current)
        count += 1

        if rule.freq == "daily":
            current += timedelta(days=rule.interval)
        elif rule.freq == "weekly":
            current += timedelta(weeks=rule.interval)
        elif rule.freq == "monthly":
            month = current.month - 1 + rule.interval
            year = current.year + month // 12
            month = month % 12 + 1
            day = min(
                current.day,
                [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1],
            )
            current = current.replace(year=year, month=month, day=day)
        elif rule.freq == "yearly":
            try:
                current = current.replace(year=current.year + rule.interval)
            except ValueError:
                current = current.replace(year=current.year + rule.interval, day=28)

    return results


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
    calendar_ids: set[str] | None = None,
    free_calendar_ids: set[str] | None = None,
) -> ScheduleResult:
    """
    Schedule pending tasks into Google Calendar.

    If task_ids is provided, only those tasks are considered.
    Otherwise, all schedulable pending tasks for the user are processed.
    """
    result = ScheduleResult()
    now = datetime.now(timezone.utc)

    # ── 1. Collect tasks ───────────────────────────────────────────────────────
    # Only query template/standalone tasks (parent_task_id IS NULL).
    # Recurring tasks are handled by scheduling one GCal event per occurrence
    # directly on the template — no child DB rows are created.
    horizon_days: int = user.preferences.get("scheduling_horizon_days", 14)
    horizon_end = now + timedelta(days=horizon_days)

    query = select(Task).where(
        Task.user_id == user.id,
        Task.schedulable == True,  # noqa: E712
        Task.status.in_([TaskStatus.PENDING, TaskStatus.SCHEDULED]),
        Task.parent_task_id.is_(None),
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

    # ── 3. Scheduling horizon already computed above ───────────────────────────

    # ── 4. Fetch free/busy from GCal ──────────────────────────────────────────
    try:
        busy_slots = await gcal.get_free_busy(
            user,
            now,
            horizon_end,
            calendar_ids=calendar_ids,
            free_calendar_ids=free_calendar_ids,
        )
    except Exception as exc:
        logger.warning("GCal free/busy fetch failed: %s", exc)
        # Fail open — mark all as skipped rather than crashing
        for task in tasks:
            result.skipped += 1
            result.details.append({"task_id": task.id, "status": "skipped", "reason": "gcal_unavailable"})
        return result

    # ── 5. Fetch blackout days ─────────────────────────────────────────────────
    tz_name = user.preferences.get("timezone", "UTC")
    try:
        user_tz: tzinfo = ZoneInfo(tz_name)
    except (KeyError, ZoneInfoNotFoundError):
        user_tz = timezone.utc
    now_local = now.astimezone(user_tz)
    horizon_end_local = horizon_end.astimezone(user_tz)
    blackout_dates = await _get_blackout_dates(db, user.id, now_local.date(), horizon_end_local.date())

    # ── 6. Parse work hours ────────────────────────────────────────────────────
    wh = user.preferences.get("work_hours", {"start": "09:00", "end": "17:00"})
    work_start = time.fromisoformat(wh["start"])
    work_end = time.fromisoformat(wh["end"])

    # ── 7. Build day-indexed free slots ───────────────────────────────────────
    # Collect all free slots across the horizon, filtered to work hours and blackout days
    all_free_slots: list[TimeSlot] = []
    current = now_local.date()
    while current <= horizon_end_local.date():
        if current not in blackout_dates:
            day_slots = get_free_slots(busy_slots, current, work_start, work_end, user_tz)
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

        # Recurring tasks: schedule one GCal event per occurrence, constrained to that day
        if task.recurrence_rule:
            await _schedule_recurring_task(
                db, gcal, user, task, all_free_slots, user_tz, horizon_end, result
            )
            continue

        # Clear any existing GCal event(s) before rescheduling
        if task.gcal_event_id:
            old_ids = task.gcal_event_id
            try:
                ids_to_delete = json.loads(old_ids) if old_ids.startswith("[") else [old_ids]
            except (ValueError, AttributeError):
                ids_to_delete = [old_ids]
            for old_eid in ids_to_delete:
                try:
                    await gcal.delete_event(user, old_eid)
                except Exception as exc:
                    logger.warning("Failed to delete old GCal event %s: %s", old_eid, exc)
            task.gcal_event_id = None

            # Restore the freed window into all_free_slots so the task can reclaim
            # its previous slot (or another task can). Without this, the slot stays
            # marked busy (from the pre-deletion free/busy fetch) and the task gets
            # pushed forward on every reschedule run.
            if task.scheduled_at and task.scheduled_end:
                freed_start = _to_utc(task.scheduled_at)
                freed_end = _to_utc(task.scheduled_end) + timedelta(minutes=task.buffer_mins)
                _restore_slot(all_free_slots, freed_start, freed_end)

        # Try to slot the task (with conflict retry)
        scheduled = False
        for attempt in range(3):
            slot = find_best_slot(task, all_free_slots)

            if slot is None and task.is_splittable:
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
                        busy_slots = await gcal.get_free_busy(
                            user,
                            now,
                            horizon_end,
                            calendar_ids=calendar_ids,
                            free_calendar_ids=free_calendar_ids,
                        )
                        all_free_slots = _recompute_free_slots(
                            busy_slots, now, horizon_end, blackout_dates, work_start, work_end, user_tz
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


async def _schedule_recurring_task(
    db: AsyncSession,
    gcal: GCalService,
    user: User,
    task: Task,
    all_free_slots: list[TimeSlot],
    user_tz: tzinfo,
    horizon_end: datetime,
    result: ScheduleResult,
) -> None:
    """Schedule a recurring task by creating one GCal event per occurrence within the horizon.

    Each occurrence is constrained to its own calendar day — no cross-day pile-up.
    All event IDs are stored as a JSON array on the task's gcal_event_id field.
    """
    now = datetime.now(timezone.utc)
    today = now.astimezone(user_tz).date()
    horizon_date = horizon_end.astimezone(user_tz).date()

    try:
        rule = RecurrenceRule.model_validate(task.recurrence_rule)
    except Exception as exc:
        logger.warning("Invalid recurrence_rule on task %s: %s", task.id, exc)
        result.skipped += 1
        result.details.append({"task_id": task.id, "status": "skipped", "reason": "invalid_recurrence_rule"})
        return

    occ_dates = _occurrence_dates(rule, today, horizon_date)

    if not occ_dates:
        result.skipped += 1
        result.details.append({"task_id": task.id, "status": "skipped", "reason": "no_occurrences_in_horizon"})
        return

    # Delete existing GCal events before rescheduling
    if task.gcal_event_id:
        try:
            ids_to_delete = json.loads(task.gcal_event_id) if task.gcal_event_id.startswith("[") else [task.gcal_event_id]
        except (ValueError, AttributeError):
            ids_to_delete = [task.gcal_event_id]
        for old_eid in ids_to_delete:
            try:
                await gcal.delete_event(user, old_eid)
            except Exception as exc:
                logger.warning("Failed to delete old GCal event %s: %s", old_eid, exc)
        task.gcal_event_id = None

        # Restore the freed window so previously occupied slots are available again.
        # For recurring tasks we only know the first occurrence's window; restore that
        # and let the remaining freed time surface naturally via slot merging.
        if task.scheduled_at and task.scheduled_end:
            freed_start = _to_utc(task.scheduled_at)
            freed_end = _to_utc(task.scheduled_end) + timedelta(minutes=task.buffer_mins)
            _restore_slot(all_free_slots, freed_start, freed_end)

    scheduled_occurrences: list[tuple[datetime, datetime, str]] = []  # (start, end, event_id)

    for occ_date in occ_dates:
        # Restrict free slots to the occurrence's own day only
        day_slots = [
            s for s in all_free_slots
            if s.start.astimezone(user_tz).date() == occ_date
        ]
        if not day_slots:
            continue  # No availability on this day — skip silently

        slot = find_best_slot(task, day_slots)
        if slot is None:
            continue  # Can't fit on this day — skip silently

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
            logger.warning("GCal create_event failed for occurrence on %s: %s", occ_date, exc)
            continue

        scheduled_occurrences.append((slot.start, slot.end, event_id))
        _consume_slot(all_free_slots, slot, task.buffer_mins)

    if not scheduled_occurrences:
        result.failed += 1
        result.details.append({"task_id": task.id, "status": "failed", "reason": "no_slots_for_any_occurrence"})
        return

    # next upcoming occurrence = earliest scheduled start
    next_start, next_end, _ = min(scheduled_occurrences, key=lambda x: x[0])
    all_event_ids = [et[2] for et in scheduled_occurrences]

    task.gcal_event_id = json.dumps(all_event_ids)
    task.scheduled_at = next_start
    task.scheduled_end = next_end
    task.status = TaskStatus.SCHEDULED

    await _log(db, user.id, task.id, "scheduled_recurring", {
        "event_ids": all_event_ids,
        "occurrences_scheduled": len(all_event_ids),
        "next_start": next_start.isoformat(),
    })

    result.scheduled += 1
    result.details.append({
        "task_id": task.id,
        "status": "scheduled",
        "occurrences_scheduled": len(all_event_ids),
        "event_ids": all_event_ids,
    })


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


def _restore_slot(
    free_slots: list[TimeSlot],
    freed_start: datetime,
    freed_end: datetime,
) -> None:
    """Re-insert a freed time window back into the free slots list, merging overlaps.

    Call this after deleting a task's old GCal event so that its previously occupied
    window is available again for the current rescheduling pass.
    freed_end should already include any buffer that was consumed.
    """
    if freed_start >= freed_end:
        return
    free_slots.append(TimeSlot(start=freed_start, end=freed_end))
    free_slots.sort(key=lambda s: s.start)
    merged: list[TimeSlot] = []
    for slot in free_slots:
        if merged and slot.start <= merged[-1].end:
            merged[-1] = TimeSlot(start=merged[-1].start, end=max(merged[-1].end, slot.end))
        else:
            merged.append(TimeSlot(start=slot.start, end=slot.end))
    free_slots[:] = [s for s in merged if s.duration_mins >= 5]


def _recompute_free_slots(
    busy: list[BusySlot],
    now: datetime,
    horizon_end: datetime,
    blackout_dates: set[date],
    work_start: time,
    work_end: time,
    tz: tzinfo = timezone.utc,
) -> list[TimeSlot]:
    """Recompute all free slots from scratch (used on conflict retry)."""
    all_free: list[TimeSlot] = []
    current = now.astimezone(tz).date()
    while current <= horizon_end.astimezone(tz).date():
        if current not in blackout_dates:
            day_slots = get_free_slots(busy, current, work_start, work_end, tz)
            clipped = [
                TimeSlot(start=max(s.start, now), end=s.end)
                for s in day_slots
                if s.end > now
            ]
            all_free.extend(s for s in clipped if s.duration_mins >= 5)
        current += timedelta(days=1)
    return all_free


# ── Schedule-on-write helper ───────────────────────────────────────────────────

async def schedule_single_task(
    db: AsyncSession,
    gcal: GCalService,
    user: User,
    task: Task,
) -> bool:
    """
    Attempt to schedule a single task immediately.

    Returns True if the task was successfully placed in GCal.
    Fails open: any error is logged and False is returned — the task
    still exists in the DB with scheduled_at=None.
    """
    try:
        result = await run_scheduler(db, gcal, user, task_ids=[task.id])
        return result.scheduled > 0
    except Exception as exc:
        logger.warning("schedule_single_task failed for task %s: %s", task.id, exc)
        return False
