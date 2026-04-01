"""Business logic for schedule windows."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.schedule_window import ScheduleWindow
from kairos.models.user import User
from kairos.schemas.schedule_window import (
    ScheduleWindowCreate,
    ScheduleWindowUpdate,
    _MAX_WINDOWS,
)


async def list_schedule_windows(db: AsyncSession, user: User) -> list[ScheduleWindow]:
    result = await db.execute(
        select(ScheduleWindow)
        .where(ScheduleWindow.user_id == user.id)
        .order_by(ScheduleWindow.created_at.asc())
    )
    return list(result.scalars().all())


async def create_schedule_window(
    db: AsyncSession,
    user: User,
    data: ScheduleWindowCreate,
) -> ScheduleWindow:
    count_result = await db.execute(
        select(func.count(ScheduleWindow.id)).where(ScheduleWindow.user_id == user.id)
    )
    if count_result.scalar_one() >= _MAX_WINDOWS:
        raise ValueError(f"Cannot create more than {_MAX_WINDOWS} schedule windows")

    window = ScheduleWindow(
        user_id=user.id,
        name=data.name,
        days_of_week=[d for d in data.days_of_week],
        start_time=data.start_time,
        end_time=data.end_time,
        color=data.color,
        is_active=data.is_active,
    )
    db.add(window)
    await db.flush()
    await db.refresh(window)
    return window


async def update_schedule_window(
    db: AsyncSession,
    user: User,
    window_id: str,
    data: ScheduleWindowUpdate,
) -> ScheduleWindow | None:
    result = await db.execute(
        select(ScheduleWindow).where(
            ScheduleWindow.id == window_id,
            ScheduleWindow.user_id == user.id,
        )
    )
    window = result.scalar_one_or_none()
    if window is None:
        return None

    update_data = data.model_dump(exclude_unset=True)

    # If only one of start_time/end_time is being updated, validate against the existing value
    new_start = update_data.get("start_time", window.start_time)
    new_end = update_data.get("end_time", window.end_time)
    if new_end <= new_start:
        raise ValueError("end_time must be strictly after start_time")

    for field, value in update_data.items():
        setattr(window, field, value)

    await db.flush()
    await db.refresh(window)
    return window


async def delete_schedule_window(
    db: AsyncSession,
    user: User,
    window_id: str,
) -> bool:
    result = await db.execute(
        select(ScheduleWindow).where(
            ScheduleWindow.id == window_id,
            ScheduleWindow.user_id == user.id,
        )
    )
    window = result.scalar_one_or_none()
    if window is None:
        return False
    await db.delete(window)
    await db.flush()
    return True
