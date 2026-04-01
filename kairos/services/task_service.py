"""Task business logic. CRUD + scheduling trigger."""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kairos.models.tag import Tag, task_tags
from kairos.models.task import Task, TaskStatus
from kairos.models.user import User
from kairos.schemas.task import TaskCreate, TaskUpdate
from kairos.utils.cuid import cuid

if TYPE_CHECKING:
    from kairos.services.gcal_service import GCalService

logger = logging.getLogger(__name__)

# Fields whose change warrants a reschedule attempt
_SCHEDULING_FIELDS = frozenset({
    "duration_mins",
    "deadline",
    "priority",
    "schedulable",
    "is_splittable",
    "min_chunk_mins",
    "buffer_mins",
    "recurrence_rule",
})


async def create_task(
    db: AsyncSession,
    user: User,
    data: TaskCreate,
    gcal: "GCalService | None" = None,
) -> Task:
    rr_dict = data.recurrence_rule.model_dump(mode="json") if data.recurrence_rule else None
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
        recurrence_rule=rr_dict,
    )
    resolved_tags: list[Tag] = []
    if data.tag_ids:
        result = await db.execute(
            select(Tag).where(Tag.id.in_(data.tag_ids), Tag.user_id == user.id)
        )
        resolved_tags = list(result.scalars().all())
        task.tags = resolved_tags
    db.add(task)
    await db.flush()

    loaded = await _load_task(db, user, task.id)  # type: ignore[arg-type]

    # Schedule-on-write: recurring tasks are scheduled by the engine the same as
    # standalone tasks (one GCal event per occurrence, no child DB rows).
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
    include_instances: bool = True,
    parent_task_id: str | None = None,
) -> tuple[list[Task], int]:
    conditions: list = [Task.user_id == user.id]

    if not include_instances:
        # Show only templates (recurrence_rule IS NOT NULL) and standalone tasks (parent_task_id IS NULL)
        conditions.append(Task.parent_task_id.is_(None))
    if parent_task_id is not None:
        conditions.append(Task.parent_task_id == parent_task_id)

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
    update_scope: Literal["this", "this_and_future", "all"] = "this",
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
    new_rr_raw = update_data.pop("recurrence_rule", ...)  # sentinel: ... means not provided

    for field, value in update_data.items():
        setattr(task, field, value)

    if metadata is not None:
        task.metadata_json = metadata

    if tag_ids is not None:
        tag_result = await db.execute(
            select(Tag).where(Tag.id.in_(tag_ids), Tag.user_id == user.id)
        )
        task.tags = list(tag_result.scalars().all())

    # ── Recurrence rule change ────────────────────────────────────────────────
    # Changing the rule (or clearing it) resets all GCal events so the scheduler
    # can create fresh events for the new pattern.
    if new_rr_raw is not ...:
        new_rr_dict = data.recurrence_rule.model_dump(mode="json") if data.recurrence_rule else None
        task.recurrence_rule = new_rr_dict

        # Remove stale GCal events — scheduler will recreate on next run
        if gcal and task.gcal_event_id:
            import json as _json
            try:
                ids_to_delete = _json.loads(task.gcal_event_id) if task.gcal_event_id.startswith("[") else [task.gcal_event_id]
            except (ValueError, AttributeError):
                ids_to_delete = [task.gcal_event_id]
            for eid in ids_to_delete:
                try:
                    await gcal.delete_event(user, eid)
                except Exception as exc:
                    logger.warning("Failed to delete GCal event %s on recurrence change: %s", eid, exc)
        task.gcal_event_id = None
        task.scheduled_at = None
        task.scheduled_end = None
        task.status = TaskStatus.PENDING
        scheduling_changed = True  # always reschedule when rule changes

    await db.flush()
    loaded = await _load_task(db, user, task_id)

    # Re-evaluate schedule if any scheduling-relevant field changed
    if gcal and loaded and scheduling_changed and loaded.schedulable and loaded.duration_mins:
        from kairos.services.scheduler import schedule_single_task
        await schedule_single_task(db, gcal, user, loaded)
        loaded = await _load_task(db, user, task_id)

    return loaded


async def delete_task(
    db: AsyncSession,
    user: User,
    task_id: str,
    scope: Literal["this", "forever"] = "this",
    gcal: "GCalService | None" = None,
) -> Task | None:
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None

    async def _cancel(t: Task, reason: str) -> None:
        """Cancel a task, removing its GCal event if present."""
        if gcal and t.gcal_event_id:
            ids_to_delete: list[str]
            try:
                import json as _json
                ids_to_delete = _json.loads(t.gcal_event_id) if t.gcal_event_id.startswith("[") else [t.gcal_event_id]
            except (ValueError, AttributeError):
                ids_to_delete = [t.gcal_event_id]
            for eid in ids_to_delete:
                try:
                    await gcal.delete_event(user, eid)
                except Exception as exc:
                    logger.warning("Failed to delete GCal event %s on task delete: %s", eid, exc)
        t.status = TaskStatus.CANCELLED
        t.gcal_event_id = None
        t.scheduled_at = None
        t.scheduled_end = None
        t.metadata_json = {**(t.metadata_json or {}), "cancellation_reason": reason}

    if scope == "forever":
        # Cancel task and all its GCal events (gcal_event_id may be a JSON array for recurring)
        await _cancel(task, "user_deleted_forever")
    else:
        await _cancel(task, "user_deleted")

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
