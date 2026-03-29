"""View business logic — CRUD and filter execution."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kairos.models.tag import Tag, task_tags
from kairos.models.task import Task
from kairos.models.user import User
from kairos.models.view import View
from kairos.schemas.view import ViewCreate, ViewUpdate

_DEFAULT_VIEWS: list[dict] = [
    {
        "name": "Today",
        "icon": "calendar-today",
        "is_default": True,
        "position": 0,
        "filter_config": {"due_within_days": 0, "status": ["pending", "scheduled"]},
        "sort_config": {"field": "priority", "direction": "asc"},
    },
    {
        "name": "This Week",
        "icon": "calendar-week",
        "is_default": True,
        "position": 1,
        "filter_config": {"due_within_days": 7, "status": ["pending", "scheduled"]},
        "sort_config": {"field": "priority", "direction": "asc"},
    },
    {
        "name": "Unscheduled",
        "icon": "inbox",
        "is_default": True,
        "position": 2,
        "filter_config": {"is_scheduled": False, "status": ["pending"]},
        "sort_config": {"field": "priority", "direction": "asc"},
    },
    {
        "name": "High Priority",
        "icon": "zap",
        "is_default": True,
        "position": 3,
        "filter_config": {"priority": [1, 2], "status": ["pending", "scheduled"]},
        "sort_config": {"field": "deadline", "direction": "asc"},
    },
]


async def seed_default_views(db: AsyncSession, user: User) -> list[View]:
    """Create the 4 default views for a new user. Idempotent — skips existing ones."""
    existing = list(
        (
            await db.execute(
                select(View).where(View.user_id == user.id, View.is_default.is_(True))
            )
        ).scalars().all()
    )
    existing_names = {v.name for v in existing}

    created: list[View] = []
    for vdef in _DEFAULT_VIEWS:
        if vdef["name"] in existing_names:
            continue
        view = View(user_id=user.id, **vdef)
        db.add(view)
        created.append(view)

    if created:
        await db.flush()
    return created


async def create_view(db: AsyncSession, user: User, data: ViewCreate) -> View:
    view = View(
        user_id=user.id,
        name=data.name,
        icon=data.icon,
        filter_config=data.filter_config,
        sort_config=data.sort_config,
        position=data.position,
    )
    db.add(view)
    await db.flush()
    await db.refresh(view)
    return view


async def list_views(db: AsyncSession, user: User) -> list[View]:
    result = await db.execute(
        select(View)
        .where(View.user_id == user.id)
        .order_by(View.position, View.created_at)
    )
    return list(result.scalars().all())


async def get_view(db: AsyncSession, user: User, view_id: str) -> View | None:
    result = await db.execute(
        select(View).where(View.id == view_id, View.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def update_view(
    db: AsyncSession, user: User, view_id: str, data: ViewUpdate
) -> View | None:
    result = await db.execute(
        select(View).where(View.id == view_id, View.user_id == user.id)
    )
    view = result.scalar_one_or_none()
    if view is None:
        return None

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(view, field, value)

    await db.flush()
    await db.refresh(view)
    return view


async def delete_view(db: AsyncSession, user: User, view_id: str) -> bool:
    result = await db.execute(
        select(View).where(View.id == view_id, View.user_id == user.id)
    )
    view = result.scalar_one_or_none()
    if view is None:
        return False
    await db.delete(view)
    await db.flush()
    return True


async def execute_view(
    db: AsyncSession, user: User, view: View
) -> tuple[list[Task], int]:
    """Execute the view's filter_config and return matching tasks + total count."""
    fc = view.filter_config
    sc = view.sort_config or {"field": "priority", "direction": "asc"}

    conditions: list = [Task.user_id == user.id]

    if "status" in fc:
        conditions.append(Task.status.in_(fc["status"]))
    if "priority" in fc:
        conditions.append(Task.priority.in_(fc["priority"]))
    if "project_id" in fc:
        conditions.append(Task.project_id == fc["project_id"])
    if "is_scheduled" in fc:
        if fc["is_scheduled"] is True:
            conditions.append(Task.scheduled_at.is_not(None))
        elif fc["is_scheduled"] is False:
            conditions.append(Task.scheduled_at.is_(None))
    if "due_within_days" in fc:
        cutoff = datetime.now(timezone.utc) + timedelta(days=fc["due_within_days"])
        conditions.append(Task.deadline <= cutoff)
    if fc.get("search"):
        term = f"%{fc['search']}%"
        conditions.append(or_(Task.title.ilike(term), Task.description.ilike(term)))

    # tags_include: task must have ALL of these tags (matched by name)
    if fc.get("tags_include"):
        tag_rows = list(
            (
                await db.execute(
                    select(Tag).where(
                        Tag.user_id == user.id, Tag.name.in_(fc["tags_include"])
                    )
                )
            ).scalars().all()
        )
        for tag in tag_rows:
            conditions.append(
                Task.id.in_(
                    select(task_tags.c.task_id).where(task_tags.c.tag_id == tag.id)
                )
            )

    # tags_exclude: task must NOT have any of these tags (matched by name)
    if fc.get("tags_exclude"):
        tag_rows = list(
            (
                await db.execute(
                    select(Tag).where(
                        Tag.user_id == user.id, Tag.name.in_(fc["tags_exclude"])
                    )
                )
            ).scalars().all()
        )
        for tag in tag_rows:
            conditions.append(
                Task.id.not_in(
                    select(task_tags.c.task_id).where(task_tags.c.tag_id == tag.id)
                )
            )

    where_clause = and_(*conditions)

    total = (
        await db.execute(select(func.count(Task.id)).where(where_clause))
    ).scalar_one()

    _sort_map = {
        "priority": Task.priority,
        "deadline": Task.deadline,
        "created_at": Task.created_at,
        "scheduled_at": Task.scheduled_at,
        "title": Task.title,
    }
    sort_col = _sort_map.get(sc.get("field", "priority"), Task.priority)
    order_expr = sort_col.asc() if sc.get("direction", "asc") == "asc" else sort_col.desc()

    result = await db.execute(
        select(Task)
        .where(where_clause)
        .options(selectinload(Task.tags))
        .order_by(order_expr)
    )
    return list(result.scalars().all()), total
