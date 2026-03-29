from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db, get_gcal_service
from kairos.models.user import User
from kairos.schemas.task import TaskCreate, TaskListResponse, TaskResponse, TaskUpdate
from kairos.services import task_service
from kairos.services.gcal_service import GCalService

router = APIRouter()


@router.post("/", response_model=TaskResponse, status_code=201)
async def create_task(
    data: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> TaskResponse:
    task = await task_service.create_task(db, current_user, data, gcal=gcal)
    return task  # type: ignore[return-value]


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    tag_ids: str | None = Query(default=None),
    is_scheduled: bool | None = Query(default=None),
    due_before: datetime | None = Query(default=None),
    due_after: datetime | None = Query(default=None),
    search: str | None = Query(default=None),
    sort: Literal["priority", "deadline", "created_at", "scheduled_at"] = Query(
        default="created_at"
    ),
    order: Literal["asc", "desc"] = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskListResponse:
    tasks, total = await task_service.list_tasks(
        db,
        current_user,
        status=status,
        priority=priority,
        project_id=project_id,
        tag_ids=tag_ids,
        is_scheduled=is_scheduled,
        due_before=due_before,
        due_after=due_after,
        search=search,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return TaskListResponse(tasks=tasks, total=total, limit=limit, offset=offset)  # type: ignore[arg-type]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    task = await task_service.get_task(db, current_user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task  # type: ignore[return-value]


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    data: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gcal: GCalService = Depends(get_gcal_service),
) -> TaskResponse:
    task = await task_service.update_task(db, current_user, task_id, data, gcal=gcal)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task  # type: ignore[return-value]


@router.delete("/{task_id}", response_model=TaskResponse)
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    task = await task_service.delete_task(db, current_user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task  # type: ignore[return-value]


@router.post("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    task = await task_service.complete_task(db, current_user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task  # type: ignore[return-value]


@router.post("/{task_id}/unschedule", response_model=TaskResponse)
async def unschedule_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskResponse:
    task = await task_service.unschedule_task(db, current_user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task  # type: ignore[return-value]
