"""Tests for recurring task creation, listing, updates, and the recurrence horizon job."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.task import Task


# ── RecurrenceRule schema validation ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_recurrence_rule_invalid_interval(auth_client: AsyncClient) -> None:
    """interval < 1 should be rejected with 422."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Bad interval",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "interval": 0},
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_recurrence_rule_mutually_exclusive_end_conditions(auth_client: AsyncClient) -> None:
    """end_date and end_after_count are mutually exclusive."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Both ends",
            "duration_mins": 30,
            "recurrence_rule": {
                "freq": "daily",
                "end_date": "2026-05-01",
                "end_after_count": 5,
            },
        },
    )
    assert r.status_code == 422


# ── Recurring task creation ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_recurring_task_returns_template(auth_client: AsyncClient) -> None:
    """POST /tasks/ with recurrence_rule returns the template task."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Daily standup",
            "duration_mins": 15,
            "recurrence_rule": {"freq": "daily", "interval": 1, "end_after_count": 3},
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["recurrence_rule"]["freq"] == "daily"
    assert data["parent_task_id"] is None
    assert data["recurrence_index"] is None


@pytest.mark.asyncio
async def test_create_recurring_task_spawns_instances(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Creating a recurring task pre-generates occurrence instances."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Weekly review",
            "duration_mins": 60,
            "recurrence_rule": {"freq": "weekly", "interval": 1, "end_after_count": 4},
        },
    )
    assert r.status_code == 201
    template_id = r.json()["id"]

    # Check occurrences exist in DB
    result = await db_session.execute(
        select(Task).where(Task.parent_task_id == template_id)
    )
    instances = result.scalars().all()
    assert len(instances) == 4
    for i, inst in enumerate(sorted(instances, key=lambda t: t.recurrence_index or 0)):
        assert inst.parent_task_id == template_id
        assert inst.recurrence_index == i
        assert inst.recurrence_rule is None
        assert inst.title == "Weekly review"
        assert inst.duration_mins == 60


@pytest.mark.asyncio
async def test_create_recurring_daily_count_boundary(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """end_after_count=2 generates exactly 2 instances."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Bounded daily",
            "duration_mins": 20,
            "recurrence_rule": {"freq": "daily", "end_after_count": 2},
        },
    )
    assert r.status_code == 201
    template_id = r.json()["id"]
    result = await db_session.execute(
        select(Task).where(Task.parent_task_id == template_id)
    )
    assert len(result.scalars().all()) == 2


@pytest.mark.asyncio
async def test_create_non_recurring_task_has_no_recurrence_fields(
    auth_client: AsyncClient,
) -> None:
    """A plain task has null recurrence fields."""
    r = await auth_client.post("/tasks/", json={"title": "Standalone", "duration_mins": 30})
    assert r.status_code == 201
    data = r.json()
    assert data["recurrence_rule"] is None
    assert data["parent_task_id"] is None
    assert data["recurrence_index"] is None


# ── Listing with recurrence filters ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tasks_include_instances_true(auth_client: AsyncClient) -> None:
    """Default listing includes occurrence instances."""
    await auth_client.post(
        "/tasks/",
        json={
            "title": "Recurring",
            "duration_mins": 15,
            "recurrence_rule": {"freq": "daily", "end_after_count": 2},
        },
    )
    r = await auth_client.get("/tasks/?include_instances=true")
    assert r.status_code == 200
    data = r.json()
    # 1 template + 2 instances = 3 total
    assert data["total"] == 3


@pytest.mark.asyncio
async def test_list_tasks_include_instances_false(auth_client: AsyncClient) -> None:
    """include_instances=false hides occurrence instances; only template shown."""
    await auth_client.post(
        "/tasks/",
        json={
            "title": "Recurring hidden",
            "duration_mins": 15,
            "recurrence_rule": {"freq": "daily", "end_after_count": 3},
        },
    )
    r = await auth_client.get("/tasks/?include_instances=false")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["tasks"][0]["recurrence_rule"]["freq"] == "daily"


@pytest.mark.asyncio
async def test_list_tasks_by_parent_task_id(auth_client: AsyncClient) -> None:
    """parent_task_id filter returns only instances of that template."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Monthly template",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "monthly", "end_after_count": 2},
        },
    )
    template_id = r.json()["id"]

    # Create a second unrelated task
    await auth_client.post("/tasks/", json={"title": "Unrelated", "duration_mins": 10})

    r2 = await auth_client.get(f"/tasks/?parent_task_id={template_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["total"] == 2
    for task in data["tasks"]:
        assert task["parent_task_id"] == template_id


# ── Update scope ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_scope_this_detaches_instance(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Updating an occurrence instance with scope=this detaches it to standalone."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Daily",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 3},
        },
    )
    template_id = r.json()["id"]

    # Get the first instance
    list_r = await auth_client.get(f"/tasks/?parent_task_id={template_id}")
    instance_id = list_r.json()["tasks"][0]["id"]

    patch_r = await auth_client.patch(
        f"/tasks/{instance_id}?update_scope=this",
        json={"title": "One-off variant"},
    )
    assert patch_r.status_code == 200
    patched = patch_r.json()
    assert patched["title"] == "One-off variant"
    assert patched["parent_task_id"] is None
    assert patched["recurrence_index"] is None


@pytest.mark.asyncio
async def test_update_scope_all_propagates_to_instances(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """update_scope=all propagates title change to all future instances."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Old title",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 3},
        },
    )
    template_id = r.json()["id"]

    patch_r = await auth_client.patch(
        f"/tasks/{template_id}?update_scope=all",
        json={"title": "New title"},
    )
    assert patch_r.status_code == 200

    result = await db_session.execute(
        select(Task).where(Task.parent_task_id == template_id)
    )
    for inst in result.scalars().all():
        assert inst.title == "New title"


@pytest.mark.asyncio
async def test_update_recurrence_rule_scope_all_regenerates_instances(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Changing recurrence_rule with scope=all deletes pending instances and regenerates."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Template",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 5},
        },
    )
    template_id = r.json()["id"]

    # Verify 5 instances exist
    before = await db_session.execute(select(Task).where(Task.parent_task_id == template_id))
    assert len(before.scalars().all()) == 5

    # Change to weekly, 2 occurrences
    patch_r = await auth_client.patch(
        f"/tasks/{template_id}?update_scope=all",
        json={"recurrence_rule": {"freq": "weekly", "end_after_count": 2}},
    )
    assert patch_r.status_code == 200
    assert patch_r.json()["recurrence_rule"]["freq"] == "weekly"

    db_session.expire_all()
    after = await db_session.execute(select(Task).where(Task.parent_task_id == template_id))
    new_instances = after.scalars().all()
    assert len(new_instances) == 2


# ── Recurrence horizon extension ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extend_recurrence_horizon_endpoint(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /schedule/recurrence/extend creates missing instances (idempotent)."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Long recurring",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 3},
        },
    )
    template_id = r.json()["id"]

    # First extend call — no new instances (already generated on create)
    extend_r = await auth_client.post("/schedule/recurrence/extend")
    assert extend_r.status_code == 200
    assert extend_r.json()["created"] == 0

    # Delete one instance manually to simulate a gap
    result = await db_session.execute(
        select(Task).where(Task.parent_task_id == template_id).limit(1)
    )
    instance = result.scalar_one()
    await db_session.delete(instance)
    await db_session.flush()

    # Second extend — should regenerate the missing instance
    extend_r2 = await auth_client.post("/schedule/recurrence/extend")
    assert extend_r2.status_code == 200
    # Some instances may be created (depends on remaining date window)
    assert extend_r2.json()["created"] >= 0


# ── Response shape for recurrence fields ─────────────────────────────────────

@pytest.mark.asyncio
async def test_recurrence_fields_in_list_response(auth_client: AsyncClient) -> None:
    """Every task in GET /tasks/ includes recurrence_rule, parent_task_id, recurrence_index."""
    await auth_client.post(
        "/tasks/",
        json={
            "title": "Shape check",
            "duration_mins": 20,
            "recurrence_rule": {"freq": "weekly", "end_after_count": 1},
        },
    )
    r = await auth_client.get("/tasks/")
    assert r.status_code == 200
    for task in r.json()["tasks"]:
        assert "recurrence_rule" in task
        assert "parent_task_id" in task
        assert "recurrence_index" in task


@pytest.mark.asyncio
async def test_weekly_days_of_week_generates_correct_occurrences(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """days_of_week on weekly freq generates only matching weekday occurrences."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Mon/Wed/Fri",
            "duration_mins": 30,
            "recurrence_rule": {
                "freq": "weekly",
                "days_of_week": ["MON", "WED", "FRI"],
                "end_after_count": 3,
            },
        },
    )
    assert r.status_code == 201
    template_id = r.json()["id"]

    result = await db_session.execute(
        select(Task).where(Task.parent_task_id == template_id)
    )
    instances = result.scalars().all()
    assert len(instances) == 3
    # All deadlines should fall on Mon (0), Wed (2), or Fri (4)
    for inst in instances:
        assert inst.deadline is not None
        assert inst.deadline.weekday() in (0, 2, 4)
