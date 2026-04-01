from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db
from kairos.models.user import User
from kairos.schemas.schedule_window import (
    ScheduleWindowCreate,
    ScheduleWindowListResponse,
    ScheduleWindowResponse,
    ScheduleWindowUpdate,
)
from kairos.services import schedule_window_service

router = APIRouter()


@router.get("/", response_model=ScheduleWindowListResponse)
async def list_schedule_windows(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScheduleWindowListResponse:
    """List all schedule windows for the current user."""
    windows = await schedule_window_service.list_schedule_windows(db, current_user)
    return ScheduleWindowListResponse(schedule_windows=windows)  # type: ignore[arg-type]


@router.post("/", response_model=ScheduleWindowResponse, status_code=201)
async def create_schedule_window(
    data: ScheduleWindowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScheduleWindowResponse:
    """Create a new schedule window.

    Returns 400 if the user already has 50 schedule windows.
    """
    try:
        window = await schedule_window_service.create_schedule_window(db, current_user, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return window  # type: ignore[return-value]


@router.patch("/{window_id}", response_model=ScheduleWindowResponse)
async def update_schedule_window(
    window_id: str,
    data: ScheduleWindowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScheduleWindowResponse:
    """Partially update a schedule window.

    If only `start_time` or only `end_time` is supplied, the update is validated
    against the existing stored value for the other field.
    """
    try:
        window = await schedule_window_service.update_schedule_window(
            db, current_user, window_id, data
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    if window is None:
        raise HTTPException(status_code=404, detail="Schedule window not found")
    return window  # type: ignore[return-value]


@router.delete("/{window_id}", status_code=204)
async def delete_schedule_window(
    window_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Permanently delete a schedule window."""
    deleted = await schedule_window_service.delete_schedule_window(db, current_user, window_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule window not found")
