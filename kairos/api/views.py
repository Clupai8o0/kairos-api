from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db
from kairos.models.user import User
from kairos.schemas.task import TaskListResponse
from kairos.schemas.view import ViewCreate, ViewListResponse, ViewResponse, ViewUpdate
from kairos.services import view_service

router = APIRouter()


@router.post("/", response_model=ViewResponse, status_code=201)
async def create_view(
    data: ViewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ViewResponse:
    view = await view_service.create_view(db, current_user, data)
    return view  # type: ignore[return-value]


@router.get("/", response_model=ViewListResponse)
async def list_views(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ViewListResponse:
    views = await view_service.list_views(db, current_user)
    return ViewListResponse(views=views)  # type: ignore[arg-type]


@router.get("/{view_id}", response_model=ViewResponse)
async def get_view(
    view_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ViewResponse:
    view = await view_service.get_view(db, current_user, view_id)
    if view is None:
        raise HTTPException(status_code=404, detail="View not found")
    return view  # type: ignore[return-value]


@router.get("/{view_id}/tasks", response_model=TaskListResponse)
async def get_view_tasks(
    view_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskListResponse:
    """Execute the view's filter and return matching tasks."""
    view = await view_service.get_view(db, current_user, view_id)
    if view is None:
        raise HTTPException(status_code=404, detail="View not found")
    tasks, total = await view_service.execute_view(db, current_user, view)
    return TaskListResponse(tasks=tasks, total=total, limit=len(tasks), offset=0)  # type: ignore[arg-type]


@router.patch("/{view_id}", response_model=ViewResponse)
async def update_view(
    view_id: str,
    data: ViewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ViewResponse:
    view = await view_service.update_view(db, current_user, view_id, data)
    if view is None:
        raise HTTPException(status_code=404, detail="View not found")
    return view  # type: ignore[return-value]


@router.delete("/{view_id}", status_code=204)
async def delete_view(
    view_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await view_service.delete_view(db, current_user, view_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="View not found")
