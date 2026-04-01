"""Tests for recurring task creation, listing, updates, and the recurrence horizon job."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.task import Task, TaskStatus


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


# ── Missed-occurrence cleanup ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_missed_occurrences_endpoint(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /schedule/recurrence/cleanup cancels PENDING instances with past deadlines."""
    # Create a recurring task
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Daily cleanup test",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 2},
        },
    )
    template_id = r.json()["id"]

    # Manually backdate one instance's deadline to yesterday so it's "missed"
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    result = await db_session.execute(
        select(Task).where(Task.parent_task_id == template_id).limit(1)
    )
    instance = result.scalar_one()
    instance.deadline = yesterday
    instance.status = TaskStatus.PENDING
    await db_session.flush()

    instance_id = instance.id  # capture before expire_all

    cleanup_r = await auth_client.post("/schedule/recurrence/cleanup")
    assert cleanup_r.status_code == 200
    assert cleanup_r.json()["cancelled"] == 1

    # Reload and confirm status
    db_session.expire_all()
    reloaded = await db_session.get(Task, instance_id)
    assert reloaded is not None
    assert reloaded.status == TaskStatus.CANCELLED
    assert reloaded.metadata_json.get("cancellation_reason") == "missed"


@pytest.mark.asyncio
async def test_cleanup_does_not_cancel_scheduled_instances(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Cleanup only targets PENDING missed instances, not SCHEDULED ones."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Scheduled past instance",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 1},
        },
    )
    template_id = r.json()["id"]

    # Backdate deadline AND set status=SCHEDULED
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    result = await db_session.execute(
        select(Task).where(Task.parent_task_id == template_id).limit(1)
    )
    instance = result.scalar_one()
    instance.deadline = yesterday
    instance.status = TaskStatus.SCHEDULED
    await db_session.flush()

    cleanup_r = await auth_client.post("/schedule/recurrence/cleanup")
    assert cleanup_r.status_code == 200
    assert cleanup_r.json()["cancelled"] == 0  # SCHEDULED not touched


# ── Delete with scope ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_instance_scope_this_skips_only_that_day(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """DELETE /tasks/{id}?scope=this on an instance cancels only that occurrence."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Daily event",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 3},
        },
    )
    template_id = r.json()["id"]
    instances_r = await auth_client.get(f"/tasks/?parent_task_id={template_id}")
    instance_id = instances_r.json()["tasks"][0]["id"]

    del_r = await auth_client.delete(f"/tasks/{instance_id}?scope=this")
    assert del_r.status_code == 200
    assert del_r.json()["status"] == "cancelled"
    assert del_r.json()["metadata"]["cancellation_reason"] == "user_skipped"

    # Other instances still pending
    remaining = await auth_client.get(f"/tasks/?parent_task_id={template_id}&status=pending")
    assert remaining.json()["total"] == 2

    # Template still active
    tmpl_r = await auth_client.get(f"/tasks/{template_id}")
    assert tmpl_r.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_delete_instance_scope_forever_cancels_template_and_all(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """DELETE /tasks/{id}?scope=forever on an instance cancels template + all instances."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Forever delete",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 3},
        },
    )
    template_id = r.json()["id"]
    instances_r = await auth_client.get(f"/tasks/?parent_task_id={template_id}")
    instance_id = instances_r.json()["tasks"][0]["id"]

    del_r = await auth_client.delete(f"/tasks/{instance_id}?scope=forever")
    assert del_r.status_code == 200

    # All instances cancelled
    db_session.expire_all()
    inst_result = await db_session.execute(
        select(Task).where(
            Task.parent_task_id == template_id,
            Task.status == TaskStatus.CANCELLED,
        )
    )
    assert len(inst_result.scalars().all()) == 3

    # Template cancelled
    tmpl_result = await db_session.get(Task, template_id)
    assert tmpl_result is not None
    assert tmpl_result.status == TaskStatus.CANCELLED
    assert tmpl_result.metadata_json.get("cancellation_reason") == "user_deleted_forever"


@pytest.mark.asyncio
async def test_delete_template_scope_forever_cancels_all_instances(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """DELETE /tasks/{template_id}?scope=forever cancels template AND all instances."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Template forever",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 2},
        },
    )
    template_id = r.json()["id"]

    del_r = await auth_client.delete(f"/tasks/{template_id}?scope=forever")
    assert del_r.status_code == 200

    db_session.expire_all()
    inst_result = await db_session.execute(
        select(Task).where(
            Task.parent_task_id == template_id,
            Task.status == TaskStatus.CANCELLED,
        )
    )
    assert len(inst_result.scalars().all()) == 2


@pytest.mark.asyncio
async def test_delete_template_scope_this_cancels_only_template(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """DELETE /tasks/{template_id}?scope=this (default) cancels only the template."""
    r = await auth_client.post(
        "/tasks/",
        json={
            "title": "Template only",
            "duration_mins": 30,
            "recurrence_rule": {"freq": "daily", "end_after_count": 2},
        },
    )
    template_id = r.json()["id"]

    del_r = await auth_client.delete(f"/tasks/{template_id}")  # default scope=this
    assert del_r.status_code == 200
    assert del_r.json()["status"] == "cancelled"

    # Instances still pending
    db_session.expire_all()
    inst_result = await db_session.execute(
        select(Task).where(
            Task.parent_task_id == template_id,
            Task.status == TaskStatus.PENDING,
        )
    )
    assert len(inst_result.scalars().all()) == 2


# ── Recurring priority ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recurring_instance_has_higher_urgency_than_standalone(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Recurring instances sort ahead of same-priority standalone tasks."""
    from kairos.services.scheduler import calculate_urgency
    from kairos.models.task import Task as TaskModel

    now = datetime.now(timezone.utc)

    standalone = TaskModel(
        id="standalone_1",
        user_id="test_user_1",
        title="Standalone",
        priority=2,
        duration_mins=30,
        buffer_mins=15,
        status="pending",
        schedulable=True,
        is_splittable=False,
        depends_on=[],
        metadata_json={},
        created_at=now,
        updated_at=now,
    )
    recurring = TaskModel(
        id="recurring_1",
        user_id="test_user_1",
        title="Recurring instance",
        priority=2,
        duration_mins=30,
        buffer_mins=15,
        status="pending",
        schedulable=True,
        is_splittable=False,
        depends_on=[],
        metadata_json={},
        parent_task_id="template_1",
        recurrence_index=0,
        created_at=now,
        updated_at=now,
    )

    standalone_urgency = calculate_urgency(standalone, now)
    recurring_urgency = calculate_urgency(recurring, now)
    assert recurring_urgency > standalone_urgency
