"""Task business logic. CRUD + scheduling trigger."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kairos.models.tag import Tag, task_tags
from kairos.models.task import Task, TaskStatus
from kairos.models.user import User
from kairos.schemas.task import TaskCreate, TaskUpdate

if TYPE_CHECKING:
    from kairos.services.gcal_service import GCalService

# Fields whose change warrants a reschedule attempt
_SCHEDULING_FIELDS = frozenset({
    "duration_mins",
    "deadline",
    "priority",
    "schedulable",
    "is_splittable",
    "min_chunk_mins",
    "buffer_mins",
})


async def create_task(
    db: AsyncSession,
    user: User,
    data: TaskCreate,
    gcal: "GCalService | None" = None,
) -> Task:
    task = Task(
        user_id=user.id,
        title=data.title,
        description=data.description,
        duration_mins=data.duration_mins,
        deadline=data.deadline,
        priority=data.priority,
        project_id=data.project_id,
        schedulable=data.schedulable,
        is_splittable=data.is_splittable,
        min_chunk_mins=data.min_chunk_mins,
        depends_on=data.depends_on,
        buffer_mins=data.buffer_mins,
        metadata_json=data.metadata,
    )
    if data.tag_ids:
        result = await db.execute(
            select(Tag).where(Tag.id.in_(data.tag_ids), Tag.user_id == user.id)
        )
        task.tags = list(result.scalars().all())
    db.add(task)
    await db.flush()

    loaded = await _load_task(db, user, task.id)  # type: ignore[arg-type]

    # Schedule-on-write: attempt to place the task in GCal immediately
    if gcal and loaded and loaded.schedulable and loaded.duration_mins:
        from kairos.services.scheduler import schedule_single_task
        await schedule_single_task(db, gcal, user, loaded)
        loaded = await _load_task(db, user, task.id)  # type: ignore[arg-type]

    return loaded  # type: ignore[return-value]


async def list_tasks(
    db: AsyncSession,
    user: User,
    *,
    status: str | None = None,
    priority: str | None = None,
    project_id: str | None = None,
    tag_ids: str | None = None,
    is_scheduled: bool | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    search: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Task], int]:
    conditions: list = [Task.user_id == user.id]

    if status:
        conditions.append(Task.status.in_([s.strip() for s in status.split(",")]))
    if priority:
        conditions.append(Task.priority.in_([int(p.strip()) for p in priority.split(",")]))
    if project_id:
        conditions.append(Task.project_id == project_id)
    if is_scheduled is True:
        conditions.append(Task.scheduled_at.is_not(None))
    elif is_scheduled is False:
        conditions.append(Task.scheduled_at.is_(None))
    if due_before:
        conditions.append(Task.deadline <= due_before)
    if due_after:
        conditions.append(Task.deadline >= due_after)
    if search:
        term = f"%{search}%"
        conditions.append(or_(Task.title.ilike(term), Task.description.ilike(term)))
    if tag_ids:
        for tid in [t.strip() for t in tag_ids.split(",")]:
            conditions.append(
                Task.id.in_(select(task_tags.c.task_id).where(task_tags.c.tag_id == tid))
            )

    where_clause = and_(*conditions)

    total = (await db.execute(select(func.count(Task.id)).where(where_clause))).scalar_one()

    _sort_map = {
        "priority": Task.priority,
        "deadline": Task.deadline,
        "created_at": Task.created_at,
        "scheduled_at": Task.scheduled_at,
    }
    sort_col = _sort_map.get(sort, Task.created_at)
    order_expr = sort_col.asc() if order == "asc" else sort_col.desc()

    result = await db.execute(
        select(Task)
        .where(where_clause)
        .options(selectinload(Task.tags))
        .order_by(order_expr)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def get_task(db: AsyncSession, user: User, task_id: str) -> Task | None:
    return await _load_task(db, user, task_id)


async def update_task(
    db: AsyncSession,
    user: User,
    task_id: str,
    data: TaskUpdate,
    gcal: "GCalService | None" = None,
) -> Task | None:
    result = await db.execute(
        select(Task)
        .where(Task.id == task_id, Task.user_id == user.id)
        .options(selectinload(Task.tags))
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    scheduling_changed = bool(set(update_data.keys()) & _SCHEDULING_FIELDS)
    tag_ids = update_data.pop("tag_ids", None)
    metadata = update_data.pop("metadata", None)

    for field, value in update_data.items():
        setattr(task, field, value)

    if metadata is not None:
        task.metadata_json = metadata

    if tag_ids is not None:
        tag_result = await db.execute(
            select(Tag).where(Tag.id.in_(tag_ids), Tag.user_id == user.id)
        )
        task.tags = list(tag_result.scalars().all())

    await db.flush()
    loaded = await _load_task(db, user, task_id)

    # Re-evaluate schedule if any scheduling-relevant field changed
    if gcal and loaded and scheduling_changed and loaded.schedulable and loaded.duration_mins:
        from kairos.services.scheduler import schedule_single_task
        await schedule_single_task(db, gcal, user, loaded)
        loaded = await _load_task(db, user, task_id)

    return loaded


async def delete_task(db: AsyncSession, user: User, task_id: str) -> Task | None:
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None
    task.status = TaskStatus.CANCELLED
    await db.flush()
    return await _load_task(db, user, task_id)


async def complete_task(db: AsyncSession, user: User, task_id: str) -> Task | None:
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None
    task.status = TaskStatus.DONE
    task.completed_at = datetime.now(tz=timezone.utc)
    await db.flush()
    return await _load_task(db, user, task_id)


async def unschedule_task(db: AsyncSession, user: User, task_id: str) -> Task | None:
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None
    task.status = TaskStatus.PENDING
    task.scheduled_at = None
    task.scheduled_end = None
    task.gcal_event_id = None
    await db.flush()
    return await _load_task(db, user, task_id)


async def _load_task(db: AsyncSession, user: User, task_id: str) -> Task | None:
    """Fetch a single task with tags eagerly loaded."""
    result = await db.execute(
        select(Task)
        .where(Task.id == task_id, Task.user_id == user.id)
        .options(selectinload(Task.tags))
    )
    return result.scalar_one_or_none()
