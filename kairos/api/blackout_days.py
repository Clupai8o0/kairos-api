import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db
from kairos.models.user import User
from kairos.schemas.blackout_day import BlackoutDayCreate, BlackoutDayResponse
from kairos.services import blackout_service

router = APIRouter()


@router.get("/", response_model=list[BlackoutDayResponse])
async def list_blackout_days(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BlackoutDayResponse]:
    days = await blackout_service.list_blackout_days(
        db, current_user, date_from=date_from, date_to=date_to
    )
    return days  # type: ignore[return-value]


@router.post("/", response_model=BlackoutDayResponse, status_code=201)
async def create_blackout_day(
    data: BlackoutDayCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlackoutDayResponse:
    try:
        day = await blackout_service.create_blackout_day(db, current_user, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return day  # type: ignore[return-value]


@router.delete("/{blackout_day_id}", status_code=204)
async def delete_blackout_day(
    blackout_day_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await blackout_service.delete_blackout_day(db, current_user, blackout_day_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Blackout day not found")

