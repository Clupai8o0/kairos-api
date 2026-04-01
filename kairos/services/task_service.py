"""Task business logic. CRUD + scheduling trigger."""

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kairos.models.tag import Tag, task_tags
from kairos.models.task import Task, TaskStatus
from kairos.models.user import User
from kairos.schemas.task import RecurrenceRule, TaskCreate, TaskUpdate
from kairos.utils.cuid import cuid

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

# How far ahead to pre-generate occurrence instances
_RECURRENCE_HORIZON_DAYS = 90


def _occurrence_dates(rule: RecurrenceRule, from_date: date, until: date, count_offset: int = 0) -> list[date]:
    """Return occurrence dates starting at from_date up to (not exceeding) until.

    count_offset: number of occurrences already generated (used for end_after_count enforcement).
    """
    results: list[date] = []
    current = from_date
    count = count_offset

    while current <= until:
        if rule.end_date and current > rule.end_date:
            break
        if rule.end_after_count is not None and count >= rule.end_after_count:
            break

        # For weekly with days_of_week, only include matching weekdays
        if rule.freq == "weekly" and rule.days_of_week:
            dow_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
            if current.weekday() in {dow_map[d] for d in rule.days_of_week if d in dow_map}:
                results.append(current)
                count += 1
            current += timedelta(days=1)
            continue

        results.append(current)
        count += 1

        if rule.freq == "daily":
            current += timedelta(days=rule.interval)
        elif rule.freq == "weekly":
            current += timedelta(weeks=rule.interval)
        elif rule.freq == "monthly":
            # Advance by N months
            month = current.month - 1 + rule.interval
            year = current.year + month // 12
            month = month % 12 + 1
            day = min(current.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
            current = current.replace(year=year, month=month, day=day)
        elif rule.freq == "yearly":
            try:
                current = current.replace(year=current.year + rule.interval)
            except ValueError:
                # Feb 29 in non-leap year → Feb 28
                current = current.replace(year=current.year + rule.interval, day=28)

    return results


async def _spawn_occurrences(
    db: AsyncSession,
    template: Task,
    rule: RecurrenceRule,
    tags: list[Tag],
    starting_index: int = 0,
    from_date: date | None = None,
    count_offset: int = 0,
) -> int:
    """Generate occurrence instances for a recurring template within the 90-day horizon.

    Returns the number of new instances created.
    """
    today = datetime.now(timezone.utc).date()
    start = from_date or today
    horizon = today + timedelta(days=_RECURRENCE_HORIZON_DAYS)

    occurrence_dates = _occurrence_dates(rule, start, horizon, count_offset=count_offset)
    created = 0

    for idx, occ_date in enumerate(occurrence_dates, start=starting_index):
        # Build a deadline at end-of-day in UTC for the occurrence date
        occ_deadline = datetime(occ_date.year, occ_date.month, occ_date.day, 23, 59, 59, tzinfo=timezone.utc)
        instance = Task(
            id=cuid(),
            user_id=template.user_id,
            project_id=template.project_id,
            title=template.title,
            description=template.description,
            duration_mins=template.duration_mins,
            deadline=occ_deadline,
            priority=template.priority,
            schedulable=template.schedulable,
            is_splittable=template.is_splittable,
            min_chunk_mins=template.min_chunk_mins,
            depends_on=[],
            buffer_mins=template.buffer_mins,
            metadata_json=dict(template.metadata_json),
            # No recurrence_rule on instances
            parent_task_id=template.id,
            recurrence_index=idx,
        )
        instance.tags = list(tags)
        db.add(instance)
        created += 1

    return created


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

    # Pre-generate occurrence instances for recurring tasks
    if data.recurrence_rule:
        await _spawn_occurrences(db, task, data.recurrence_rule, resolved_tags)
        await db.flush()

    loaded = await _load_task(db, user, task.id)  # type: ignore[arg-type]

    # Schedule-on-write: only schedule the template itself when non-recurring,
    # or skip — instances are scheduled by the batch scheduler run.
    if gcal and loaded and loaded.schedulable and loaded.duration_mins and not data.recurrence_rule:
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

    # ── Recurrence rule change on a template ──────────────────────────────────
    if new_rr_raw is not ...:
        new_rr_obj: RecurrenceRule | None = data.recurrence_rule
        new_rr_dict = new_rr_obj.model_dump(mode="json") if new_rr_obj else None
        task.recurrence_rule = new_rr_dict

        is_template = task.parent_task_id is None
        if is_template and update_scope in ("all", "this_and_future"):
            # Delete future instances and regenerate from today
            today = datetime.now(timezone.utc).date()
            existing = await db.execute(
                select(Task).where(
                    Task.parent_task_id == task.id,
                    Task.user_id == user.id,
                    Task.status.not_in([TaskStatus.DONE, TaskStatus.CANCELLED]),
                )
            )
            for inst in existing.scalars().all():
                await db.delete(inst)
            if new_rr_obj:
                await db.flush()
                tag_result2 = await db.execute(
                    select(Tag).where(Tag.id.in_([t.id for t in task.tags]), Tag.user_id == user.id)
                )
                await _spawn_occurrences(db, task, new_rr_obj, list(tag_result2.scalars().all()), from_date=today)

    # ── Detach occurrence instance when updated with scope=this ───────────────
    elif task.parent_task_id is not None and update_scope == "this":
        # Non-recurrence fields updated on an instance → detach it to standalone
        task.parent_task_id = None
        task.recurrence_index = None

    elif task.parent_task_id is None and task.recurrence_rule and update_scope in ("all", "this_and_future"):
        # Updating fields on template — propagate to future pending instances
        propagate_fields = {k: v for k, v in update_data.items() if k not in ("status",)}
        if propagate_fields or tag_ids is not None or metadata is not None:
            today = datetime.now(timezone.utc).date()
            inst_result = await db.execute(
                select(Task)
                .where(
                    Task.parent_task_id == task.id,
                    Task.user_id == user.id,
                    Task.status.not_in([TaskStatus.DONE, TaskStatus.CANCELLED]),
                )
                .options(selectinload(Task.tags))
            )
            for inst in inst_result.scalars().all():
                for field, value in propagate_fields.items():
                    setattr(inst, field, value)
                if metadata is not None:
                    inst.metadata_json = metadata
                if tag_ids is not None:
                    inst.tags = list(task.tags)

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


async def extend_recurrence_horizon(db: AsyncSession) -> int:
    """Extend occurrence instances for all active recurring templates up to the 90-day horizon.

    Designed to be called by a daily background job. Returns the total number of
    new instances created across all users.
    """
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=_RECURRENCE_HORIZON_DAYS)
    total_created = 0

    # Find all recurring templates (parent_task_id IS NULL, recurrence_rule IS NOT NULL)
    templates_result = await db.execute(
        select(Task)
        .where(
            Task.parent_task_id.is_(None),
            Task.recurrence_rule.is_not(None),
            Task.status.not_in([TaskStatus.DONE, TaskStatus.CANCELLED]),
        )
        .options(selectinload(Task.tags))
    )
    templates = list(templates_result.scalars().all())

    for template in templates:
        try:
            rule = RecurrenceRule.model_validate(template.recurrence_rule)
        except Exception:
            continue  # Bad data — skip silently

        # Find the latest existing instance date to avoid duplicates
        latest_result = await db.execute(
            select(Task.deadline)
            .where(Task.parent_task_id == template.id)
            .order_by(Task.deadline.desc())
            .limit(1)
        )
        latest_row = latest_result.scalar_one_or_none()
        if latest_row:
            # Start generating from the day after the latest instance
            latest_date = latest_row.date() if hasattr(latest_row, "date") else latest_row
            from_date = latest_date + timedelta(days=1)
        else:
            from_date = today

        if from_date > horizon:
            continue  # Already covered

        # Determine next recurrence_index
        count_result = await db.execute(
            select(func.count(Task.id)).where(Task.parent_task_id == template.id)
        )
        existing_count = count_result.scalar_one()

        created = await _spawn_occurrences(
            db, template, rule, list(template.tags),
            starting_index=existing_count,
            from_date=from_date,
            count_offset=existing_count,
        )
        total_created += created

    await db.flush()
    return total_created
