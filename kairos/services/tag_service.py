"""Tag business logic."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.tag import Tag, project_tags, task_tags
from kairos.models.user import User
from kairos.schemas.tag import TagCreate, TagUpdate


async def create_tag(
    db: AsyncSession, user: User, data: TagCreate
) -> Tag | None:
    """Create a tag. Returns None if name already exists for this user."""
    tag = Tag(
        user_id=user.id,
        name=data.name.strip(),
        color=data.color,
        icon=data.icon,
    )
    db.add(tag)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return None
    await db.refresh(tag)
    return tag


async def list_tags(
    db: AsyncSession, user: User
) -> list[tuple[Tag, int, int]]:
    """Return all tags for the user with task/project usage counts."""
    task_count_sq = (
        select(func.count())
        .where(task_tags.c.tag_id == Tag.id)
        .correlate(Tag)
        .scalar_subquery()
    )
    project_count_sq = (
        select(func.count())
        .where(project_tags.c.tag_id == Tag.id)
        .correlate(Tag)
        .scalar_subquery()
    )

    result = await db.execute(
        select(Tag, task_count_sq.label("task_count"), project_count_sq.label("project_count"))
        .where(Tag.user_id == user.id)
        .order_by(Tag.name)
    )
    return list(result.all())


async def update_tag(
    db: AsyncSession, user: User, tag_id: str, data: TagUpdate
) -> Tag | None:
    """Update a tag. Returns None if not found. Returns None (duplicate) on name conflict."""
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.user_id == user.id)
    )
    tag = result.scalar_one_or_none()
    if tag is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "name" and value is not None:
            value = value.strip()
        setattr(tag, field, value)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise

    await db.refresh(tag)
    return tag


async def delete_tag(db: AsyncSession, user: User, tag_id: str) -> bool:
    """Hard delete a tag. Returns True if deleted, False if not found.
    Junction table rows are removed by ON DELETE CASCADE.
    """
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.user_id == user.id)
    )
    tag = result.scalar_one_or_none()
    if tag is None:
        return False
    await db.delete(tag)
    await db.flush()
    return True
