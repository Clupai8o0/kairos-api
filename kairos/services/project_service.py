"""Project business logic."""

from sqlalchemy import and_, func, or_, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kairos.models.project import Project, ProjectStatus
from kairos.models.tag import Tag, project_tags
from kairos.models.task import Task
from kairos.models.user import User
from kairos.schemas.project import ProjectCreate, ProjectUpdate


async def create_project(db: AsyncSession, user: User, data: ProjectCreate) -> Project:
    project = Project(
        user_id=user.id,
        title=data.title,
        description=data.description,
        deadline=data.deadline,
        color=data.color,
        metadata_json=data.metadata,
    )
    if data.tag_ids:
        result = await db.execute(
            select(Tag).where(Tag.id.in_(data.tag_ids), Tag.user_id == user.id)
        )
        project.tags = list(result.scalars().all())
    db.add(project)
    await db.flush()
    return await _load_project(db, user, project.id)  # type: ignore[arg-type]


async def list_projects(
    db: AsyncSession,
    user: User,
    *,
    status: str | None = None,
    search: str | None = None,
    tag_ids: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Project], int]:
    conditions: list = [Project.user_id == user.id]

    if status:
        conditions.append(Project.status.in_([s.strip() for s in status.split(",")]))
    if search:
        term = f"%{search}%"
        conditions.append(or_(Project.title.ilike(term), Project.description.ilike(term)))
    if tag_ids:
        for tid in [t.strip() for t in tag_ids.split(",")]:
            conditions.append(
                Project.id.in_(
                    select(project_tags.c.project_id).where(project_tags.c.tag_id == tid)
                )
            )

    where_clause = and_(*conditions)

    total = (
        await db.execute(select(func.count(Project.id)).where(where_clause))
    ).scalar_one()

    _sort_map = {
        "title": Project.title,
        "deadline": Project.deadline,
        "created_at": Project.created_at,
        "status": Project.status,
    }
    sort_col = _sort_map.get(sort, Project.created_at)
    order_expr = sort_col.asc() if order == "asc" else sort_col.desc()

    result = await db.execute(
        select(Project)
        .where(where_clause)
        .options(selectinload(Project.tags))
        .order_by(order_expr)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def get_project(db: AsyncSession, user: User, project_id: str) -> Project | None:
    return await _load_project_with_tasks(db, user, project_id)


async def update_project(
    db: AsyncSession, user: User, project_id: str, data: ProjectUpdate
) -> Project | None:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id, Project.user_id == user.id)
        .options(selectinload(Project.tags))
    )
    project = result.scalar_one_or_none()
    if project is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    tag_ids = update_data.pop("tag_ids", None)
    metadata = update_data.pop("metadata", None)

    for field, value in update_data.items():
        setattr(project, field, value)

    if metadata is not None:
        project.metadata_json = metadata

    if tag_ids is not None:
        tag_result = await db.execute(
            select(Tag).where(Tag.id.in_(tag_ids), Tag.user_id == user.id)
        )
        project.tags = list(tag_result.scalars().all())

    await db.flush()
    return await _load_project(db, user, project_id)


async def delete_project(db: AsyncSession, user: User, project_id: str) -> Project | None:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        return None

    project.status = ProjectStatus.ARCHIVED

    # Tasks remain but lose their project association (per API contract)
    await db.execute(
        sa_update(Task)
        .where(Task.project_id == project_id)
        .values(project_id=None)
    )

    await db.flush()
    return await _load_project(db, user, project_id)


async def list_project_tasks(
    db: AsyncSession,
    user: User,
    project_id: str,
    **kwargs,
) -> tuple[list[Task], int] | None:
    """Return tasks for a project, or None if the project doesn't belong to the user."""
    exists = (
        await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user.id)
        )
    ).scalar_one_or_none()
    if exists is None:
        return None

    from kairos.services import task_service  # local import to avoid potential circularity

    return await task_service.list_tasks(db, user, project_id=project_id, **kwargs)


# ── Private helpers ────────────────────────────────────────────────────────────


async def _load_project(db: AsyncSession, user: User, project_id: str) -> Project | None:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id, Project.user_id == user.id)
        .options(selectinload(Project.tags))
    )
    return result.scalar_one_or_none()


async def _load_project_with_tasks(
    db: AsyncSession, user: User, project_id: str
) -> Project | None:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id, Project.user_id == user.id)
        .options(selectinload(Project.tags), selectinload(Project.tasks))
    )
    return result.scalar_one_or_none()
