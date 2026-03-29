from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db
from kairos.models.user import User
from kairos.schemas.tag import (
    TagCreate,
    TagListResponse,
    TagResponse,
    TagUpdate,
    TagWithCountsResponse,
)
from kairos.services import tag_service

router = APIRouter()


@router.post("/", response_model=TagResponse, status_code=201)
async def create_tag(
    data: TagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    """Create a tag. Returns 409 if a tag with that name already exists.

    Use a consistent naming convention to keep tags organised:
    `area:work`, `context:laptop`, `type:deep-work`.
    """
    tag = await tag_service.create_tag(db, current_user, data)
    if tag is None:
        raise HTTPException(status_code=409, detail="Tag name already exists")
    return tag  # type: ignore[return-value]


@router.get("/", response_model=TagListResponse)
async def list_tags(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TagListResponse:
    """List all tags with usage counts (`task_count`, `project_count`)."""
    rows = await tag_service.list_tags(db, current_user)
    tags = [
        TagWithCountsResponse(
            id=tag.id,
            user_id=tag.user_id,
            name=tag.name,
            color=tag.color,
            icon=tag.icon,
            created_at=tag.created_at,
            task_count=task_count,
            project_count=project_count,
        )
        for tag, task_count, project_count in rows
    ]
    return TagListResponse(tags=tags)


@router.patch("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: str,
    data: TagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    """Update a tag's name, colour, or icon. Returns 409 if the new name conflicts."""
    try:
        tag = await tag_service.update_tag(db, current_user, tag_id, data)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Tag name already exists")
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag  # type: ignore[return-value]


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Hard-delete a tag and remove it from all task and project associations."""
    deleted = await tag_service.delete_tag(db, current_user, tag_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found")
