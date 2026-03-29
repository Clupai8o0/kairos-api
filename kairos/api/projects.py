from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db
from kairos.models.user import User
from kairos.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
    ProjectWithTasksResponse,
)
from kairos.schemas.task import TaskListResponse
from kairos.services import project_service

router = APIRouter()


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    project = await project_service.create_project(db, current_user, data)
    return project  # type: ignore[return-value]


@router.get("/", response_model=ProjectListResponse)
async def list_projects(
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    tag_ids: str | None = Query(default=None),
    sort: Literal["title", "deadline", "created_at", "status"] = Query(default="created_at"),
    order: Literal["asc", "desc"] = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectListResponse:
    projects, total = await project_service.list_projects(
        db,
        current_user,
        status=status,
        search=search,
        tag_ids=tag_ids,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return ProjectListResponse(projects=projects, total=total, limit=limit, offset=offset)  # type: ignore[arg-type]


@router.get("/{project_id}", response_model=ProjectWithTasksResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectWithTasksResponse:
    project = await project_service.get_project(db, current_user, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project  # type: ignore[return-value]


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    project = await project_service.update_project(db, current_user, project_id, data)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project  # type: ignore[return-value]


@router.delete("/{project_id}", response_model=ProjectResponse)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    project = await project_service.delete_project(db, current_user, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project  # type: ignore[return-value]


@router.get("/{project_id}/tasks", response_model=TaskListResponse)
async def list_project_tasks(
    project_id: str,
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    sort: Literal["priority", "deadline", "created_at", "scheduled_at"] = Query(
        default="created_at"
    ),
    order: Literal["asc", "desc"] = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskListResponse:
    result = await project_service.list_project_tasks(
        db,
        current_user,
        project_id,
        status=status,
        priority=priority,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    tasks, total = result
    return TaskListResponse(tasks=tasks, total=total, limit=limit, offset=offset)  # type: ignore[arg-type]
