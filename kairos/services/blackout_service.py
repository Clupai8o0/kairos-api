"""Blackout day business logic."""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.blackout_day import BlackoutDay
from kairos.models.user import User
from kairos.schemas.blackout_day import BlackoutDayCreate


async def create_blackout_day(
    db: AsyncSession,
    user: User,
    data: BlackoutDayCreate,
) -> BlackoutDay:
    """Create a blackout day. Raises ValueError on duplicate date."""
    day = BlackoutDay(user_id=user.id, date=data.date, reason=data.reason)
    db.add(day)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ValueError(f"Blackout day already exists for {data.date}")
    await db.refresh(day)
    return day


async def list_blackout_days(
    db: AsyncSession,
    user: User,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> list[BlackoutDay]:
    """Return all blackout days for the user, optionally filtered by date range."""
    stmt = select(BlackoutDay).where(BlackoutDay.user_id == user.id)
    if date_from is not None:
        stmt = stmt.where(BlackoutDay.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(BlackoutDay.date <= date_to)
    stmt = stmt.order_by(BlackoutDay.date)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_blackout_day(
    db: AsyncSession,
    user: User,
    blackout_day_id: str,
) -> bool:
    """Delete a blackout day. Returns False if not found."""
    result = await db.execute(
        select(BlackoutDay).where(
            BlackoutDay.id == blackout_day_id,
            BlackoutDay.user_id == user.id,
        )
    )
    day = result.scalar_one_or_none()
    if day is None:
        return False
    await db.delete(day)
    await db.flush()
    return True
