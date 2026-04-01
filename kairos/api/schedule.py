"""Schedule API — trigger scheduling runs, query slots and today's agenda."""

import logging
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, HTTPException, Query, status
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db, get_gcal_service
from kairos.models.task import Task, TaskStatus
from kairos.models.user import User
from kairos.schemas.schedule import (
    FreeSlotResponse,
    ScheduledTaskResponse,
    ScheduleItem,
    ScheduleRunRequest,
    ScheduleRunResponse,
    ScheduleTodayResponse,
)
from kairos.schemas.task import TaskResponse
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
    calendar_ids = set(payload.calendar_ids) if payload.calendar_ids else None
    free_calendar_ids = set(payload.free_calendar_ids) if payload.free_calendar_ids else None
    if calendar_ids and free_calendar_ids:
        free_calendar_ids = free_calendar_ids & calendar_ids
    result = await run_scheduler(
        db,
        gcal,
        user,
        task_ids=payload.task_ids,
        calendar_ids=calendar_ids,
        free_calendar_ids=free_calendar_ids,
    )
    return ScheduleRunResponse(
        scheduled=result.scheduled,
        failed=result.failed,
        skipped=result.skipped,
        details=result.details,
    )


@router.get("/today", response_model=ScheduleTodayResponse)
async def schedule_today(
    day: str | None = Query(default=None, description="YYYY-MM-DD in user timezone"),
    task_events: Literal["exclude", "include"] = Query(
        default="exclude",
        description="exclude=hide task-backed calendar events, include=return them with flags",
    ),
    calendar_ids: str | None = Query(
        default=None,
        description="Comma-separated calendar IDs to include for this schedule view",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> ScheduleTodayResponse:
    """Return all tasks scheduled for today as a `ScheduleTodayResponse`.

    Task and Google Calendar event items are merged in one timeline.
    Task items remain visible for task-native editing. By default, calendar
    events that are task-backed are excluded (`task_events=exclude`).
    """
    tz_name = user.preferences.get("timezone", "UTC")
    try:
        user_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_timezone",
                "message": f"Unsupported timezone: {tz_name}",
            },
        ) from exc

    if day:
        try:
            local_start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=user_tz)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "invalid_date",
                    "message": "day must be YYYY-MM-DD",
                },
            ) from exc
    else:
        local_start = datetime.now(user_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)

    start = local_start.astimezone(timezone.utc)
    end = local_end.astimezone(timezone.utc)

    include_task_events = task_events == "include"
    selected_calendar_ids = set(c.strip() for c in calendar_ids.split(",") if c.strip()) if calendar_ids else None

    rows = await db.execute(
        select(Task)
        .where(
            Task.user_id == user.id,
            Task.scheduled_at >= start,
            Task.scheduled_at < end,
            Task.status != TaskStatus.CANCELLED,
        )
        .options(selectinload(Task.tags))
        .order_by(Task.scheduled_at)
    )
    tasks = rows.scalars().all()
    items: list[ScheduleItem] = [
        ScheduleItem(type="task", task=TaskResponse.model_validate(t))
        for t in tasks
        if t.scheduled_at and t.scheduled_end
    ]

    try:
        events = await gcal.get_schedule_events(
            user,
            start,
            end,
            include_task_events=include_task_events,
            calendar_ids=selected_calendar_ids,
        )
    except GCalAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "google_auth_required",
                "message": str(exc),
            },
        ) from exc

    for event in events:
        items.append(
            ScheduleItem(
                type="event",
                gcal_event={
                    "event_id": event.event_id,
                    "provider": "google",
                    "account_id": event.account_id,
                    "calendar_id": event.calendar_id,
                    "calendar_name": event.calendar_name,
                    "summary": event.summary,
                    "description": event.description,
                    "location": event.location,
                    "start": event.start,
                    "end": event.end,
                    "timezone": event.timezone,
                    "is_all_day": event.is_all_day,
                    "is_recurring_instance": event.is_recurring_instance,
                    "recurring_event_id": event.recurring_event_id,
                    "html_link": event.html_link,
                    "can_edit": event.can_edit,
                    "etag": event.etag,
                    "is_task_event": event.is_task_event,
                    "task_id": event.task_id,
                    "transparency": event.transparency,
                },
            )
        )

    items.sort(
        key=lambda item: (
            item.task.scheduled_at if item.task else item.gcal_event.start,  # type: ignore[union-attr]
            item.type,
        )
    )
    return ScheduleTodayResponse(date=local_start.date().isoformat(), items=items)


@router.get("/week", response_model=list[ScheduleTodayResponse])
async def schedule_week(
    start_date: str | None = Query(default=None, description="YYYY-MM-DD in user timezone"),
    end_date: str | None = Query(default=None, description="YYYY-MM-DD exclusive in user timezone"),
    task_events: Literal["exclude", "include"] = Query(
        default="exclude",
        description="exclude=hide task-backed calendar events, include=return them with flags",
    ),
    calendar_ids: str | None = Query(
        default=None,
        description="Comma-separated calendar IDs to include for this schedule view",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> list[ScheduleTodayResponse]:
    """Return the current week's schedule (Mon–Sun) grouped by day.

    Returns one `ScheduleTodayResponse` per day that has at least one item.
    Task items remain visible; task-backed calendar events are excluded by default.
    """
    tz_name = user.preferences.get("timezone", "UTC")
    try:
        user_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_timezone", "message": f"Unsupported timezone: {tz_name}"},
        ) from exc

    if start_date:
        try:
            local_start = datetime.fromisoformat(f"{start_date}T00:00:00").replace(tzinfo=user_tz)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_date", "message": "start_date must be YYYY-MM-DD"},
            ) from exc
    else:
        now_local = datetime.now(user_tz)
        local_start = (now_local - timedelta(days=now_local.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    if end_date:
        try:
            local_end = datetime.fromisoformat(f"{end_date}T00:00:00").replace(tzinfo=user_tz)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_date", "message": "end_date must be YYYY-MM-DD"},
            ) from exc
    else:
        local_end = local_start + timedelta(days=7)

    if local_end <= local_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_range", "message": "end_date must be after start_date"},
        )

    start = local_start.astimezone(timezone.utc)
    end = local_end.astimezone(timezone.utc)

    include_task_events = task_events == "include"
    selected_calendar_ids = set(c.strip() for c in calendar_ids.split(",") if c.strip()) if calendar_ids else None

    rows = await db.execute(
        select(Task)
        .where(
            Task.user_id == user.id,
            Task.scheduled_at >= start,
            Task.scheduled_at < end,
            Task.status != TaskStatus.CANCELLED,
        )
        .options(selectinload(Task.tags))
        .order_by(Task.scheduled_at)
    )
    tasks = [t for t in rows.scalars().all() if t.scheduled_at and t.scheduled_end]

    by_date: dict[str, list[ScheduleItem]] = defaultdict(list)
    for t in tasks:
        day = t.scheduled_at.astimezone(user_tz).date().isoformat()  # type: ignore[union-attr]
        by_date[day].append(ScheduleItem(type="task", task=TaskResponse.model_validate(t)))

    try:
        events = await gcal.get_schedule_events(
            user,
            start,
            end,
            include_task_events=include_task_events,
            calendar_ids=selected_calendar_ids,
        )
    except GCalAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "google_auth_required", "message": str(exc)},
        ) from exc

    for event in events:
        day = event.start.astimezone(user_tz).date().isoformat()
        by_date[day].append(
            ScheduleItem(
                type="event",
                gcal_event={
                    "event_id": event.event_id,
                    "provider": "google",
                    "account_id": event.account_id,
                    "calendar_id": event.calendar_id,
                    "calendar_name": event.calendar_name,
                    "summary": event.summary,
                    "description": event.description,
                    "location": event.location,
                    "start": event.start,
                    "end": event.end,
                    "timezone": event.timezone,
                    "is_all_day": event.is_all_day,
                    "is_recurring_instance": event.is_recurring_instance,
                    "recurring_event_id": event.recurring_event_id,
                    "html_link": event.html_link,
                    "can_edit": event.can_edit,
                    "etag": event.etag,
                    "is_task_event": event.is_task_event,
                    "task_id": event.task_id,
                    "transparency": event.transparency,
                },
            )
        )

    return [
        ScheduleTodayResponse(
            date=day,
            items=sorted(
                items,
                key=lambda item: (
                    item.task.scheduled_at if item.task else item.gcal_event.start,  # type: ignore[union-attr]
                    item.type,
                ),
            ),
        )
        for day, items in sorted(by_date.items())
    ]


@router.get("/free-slots", response_model=list[FreeSlotResponse])
async def free_slots(
    days: int = 7,
    calendar_ids: str | None = Query(
        default=None,
        description="Comma-separated calendar IDs to include when computing busy windows",
    ),
    free_calendar_ids: str | None = Query(
        default=None,
        description="Comma-separated calendar IDs treated as free for slot computation",
    ),
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
    selected_calendar_ids = set(c.strip() for c in calendar_ids.split(",") if c.strip()) if calendar_ids else None
    selected_free_calendar_ids = (
        set(c.strip() for c in free_calendar_ids.split(",") if c.strip())
        if free_calendar_ids
        else None
    )
    if selected_calendar_ids and selected_free_calendar_ids:
        selected_free_calendar_ids = selected_free_calendar_ids & selected_calendar_ids

    try:
        busy = await gcal.get_free_busy(
            user,
            now,
            horizon_end,
            calendar_ids=selected_calendar_ids,
            free_calendar_ids=selected_free_calendar_ids,
        )
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
    tz_name = user.preferences.get("timezone", "UTC")
    try:
        user_tz = ZoneInfo(tz_name)
    except (KeyError, ZoneInfoNotFoundError):
        user_tz = timezone.utc
    now_local = now.astimezone(user_tz)
    horizon_end_local = horizon_end.astimezone(user_tz)

    slots: list[FreeSlotResponse] = []
    current = now_local.date()
    while current <= horizon_end_local.date():
        if current.weekday() < 5:
            day_slots = get_free_slots(busy, current, work_start, work_end, user_tz)
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


@router.post("/recurrence/extend", status_code=200)
async def extend_recurrence_horizon(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Extend occurrence instances for recurring templates up to the 90-day horizon.

    Safe to call repeatedly — only creates missing instances, never duplicates.
    Intended for daily cron use but also callable on-demand.
    """
    from kairos.services.task_service import extend_recurrence_horizon as _extend
    created = await _extend(db)
    return {"created": created}

