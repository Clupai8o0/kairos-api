"""Schedule API — trigger scheduling runs, query slots and today's agenda."""

import logging
from datetime import datetime, time, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db, get_gcal_service
from kairos.models.task import Task, TaskStatus
from kairos.models.user import User
from kairos.schemas.schedule import (
    FreeSlotResponse,
    ScheduledTaskResponse,
    ScheduleRunRequest,
    ScheduleRunResponse,
)
from kairos.services.gcal_service import GCalAuthError, GCalService
from kairos.services.scheduler import (
    TimeSlot,
    get_free_slots,
    run_scheduler,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/run", response_model=ScheduleRunResponse)
async def run_schedule(
    payload: ScheduleRunRequest = ScheduleRunRequest(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> ScheduleRunResponse:
    """Trigger a full reschedule for pending/scheduled tasks.

    - Omit `task_ids` to reschedule **all** pending tasks.
    - Supply `task_ids` to reschedule only those tasks.
    - `dry_run=true` returns what would change without writing to Google Calendar.

    The response includes `scheduled` (placed), `failed` (no slot found before deadline),
    `skipped` (dependencies unmet or already done), and `details`.
    """
    result = await run_scheduler(db, gcal, user, task_ids=payload.task_ids)
    return ScheduleRunResponse(
        scheduled=result.scheduled,
        failed=result.failed,
        skipped=result.skipped,
        details=result.details,
    )


@router.get("/today", response_model=list[ScheduledTaskResponse])
async def schedule_today(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ScheduledTaskResponse]:
    """Return all tasks scheduled for today, ordered by start time."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    rows = await db.execute(
        select(Task).where(
            Task.user_id == user.id,
            Task.scheduled_at >= start,
            Task.scheduled_at < end,
            Task.status != TaskStatus.CANCELLED,
        ).order_by(Task.scheduled_at)
    )
    tasks = rows.scalars().all()
    return [
        ScheduledTaskResponse(
            task_id=t.id,
            title=t.title,
            start=t.scheduled_at,
            end=t.scheduled_end,
            gcal_event_id=t.gcal_event_id,
        )
        for t in tasks
        if t.scheduled_at and t.scheduled_end
    ]


@router.get("/week", response_model=list[ScheduledTaskResponse])
async def schedule_week(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ScheduledTaskResponse]:
    """Return all tasks scheduled for the current week (Mon–Sun), ordered by start time."""
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)

    rows = await db.execute(
        select(Task).where(
            Task.user_id == user.id,
            Task.scheduled_at >= start,
            Task.scheduled_at < end,
            Task.status != TaskStatus.CANCELLED,
        ).order_by(Task.scheduled_at)
    )
    tasks = rows.scalars().all()
    return [
        ScheduledTaskResponse(
            task_id=t.id,
            title=t.title,
            start=t.scheduled_at,
            end=t.scheduled_end,
            gcal_event_id=t.gcal_event_id,
        )
        for t in tasks
        if t.scheduled_at and t.scheduled_end
    ]


@router.get("/free-slots", response_model=list[FreeSlotResponse])
async def free_slots(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> list[FreeSlotResponse]:
    """Return available time slots within the next N days.

    Only slots within the user's configured work hours are included.
    Weekends are excluded. Returned slots are already clipped to the current time
    (no past slots). `days` is clamped to 1–30.

    If Google Calendar is unavailable, returns an empty list (does not error).
    """
    now = datetime.now(timezone.utc)
    horizon_end = now + timedelta(days=max(1, min(days, 30)))

    try:
        busy = await gcal.get_free_busy(user, now, horizon_end)
    except GCalAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.warning("free-slots: GCal unavailable: %s", exc)
        return []

    wh = user.preferences.get("work_hours", {"start": "09:00", "end": "17:00"})
    work_start = time.fromisoformat(wh["start"])
    work_end = time.fromisoformat(wh["end"])

    slots: list[FreeSlotResponse] = []
    current = now.date()
    while current <= horizon_end.date():
        if current.weekday() < 5:
            day_slots = get_free_slots(busy, current, work_start, work_end)
            for s in day_slots:
                clipped_start = max(s.start, now)
                if clipped_start < s.end:
                    slots.append(
                        FreeSlotResponse(
                            start=clipped_start,
                            end=s.end,
                            duration_mins=round((s.end - clipped_start).total_seconds() / 60, 1),
                        )
                    )
        current += timedelta(days=1)

    return slots

