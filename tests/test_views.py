from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.user import User


# ── Auth guards ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_views_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get("/views/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_view_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.post(
        "/views/", json={"name": "My View", "filter_config": {}}
    )
    assert response.status_code == 401


# ── Create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_view(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/views/",
        json={
            "name": "Deep Work This Week",
            "icon": "brain",
            "filter_config": {
                "tags_include": ["type:deep-work"],
                "due_within_days": 7,
                "status": ["pending", "scheduled"],
            },
            "sort_config": {"field": "priority", "direction": "asc"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Deep Work This Week"
    assert data["icon"] == "brain"
    assert data["filter_config"]["due_within_days"] == 7
    assert data["is_default"] is False
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_view_minimal(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/views/", json={"name": "My View", "filter_config": {}}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["sort_config"] == {"field": "priority", "direction": "asc"}
    assert data["position"] == 0


@pytest.mark.asyncio
async def test_create_view_empty_name_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/views/", json={"name": "", "filter_config": {}}
    )
    assert response.status_code == 422


# ── List ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_views_empty(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/views/")
    assert response.status_code == 200
    data = response.json()
    assert data["views"] == []


@pytest.mark.asyncio
async def test_list_views_ordered_by_position(auth_client: AsyncClient) -> None:
    await auth_client.post("/views/", json={"name": "C", "filter_config": {}, "position": 2})
    await auth_client.post("/views/", json={"name": "A", "filter_config": {}, "position": 0})
    await auth_client.post("/views/", json={"name": "B", "filter_config": {}, "position": 1})

    response = await auth_client.get("/views/")
    assert response.status_code == 200
    names = [v["name"] for v in response.json()["views"]]
    assert names == ["A", "B", "C"]


# ── Get ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_view(auth_client: AsyncClient) -> None:
    create_resp = await auth_client.post(
        "/views/",
        json={
            "name": "My View",
            "filter_config": {"status": ["pending"]},
            "sort_config": {"field": "deadline", "direction": "desc"},
        },
    )
    view_id = create_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "My View"
    assert data["filter_config"] == {"status": ["pending"]}
    assert data["sort_config"] == {"field": "deadline", "direction": "desc"}


@pytest.mark.asyncio
async def test_get_nonexistent_view_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/views/does_not_exist")
    assert response.status_code == 404


# ── Execute (GET /:id/tasks) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_view_returns_matching_tasks(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "Pending task", "priority": 3})
    await auth_client.post("/tasks/", json={"title": "Done task", "priority": 3})

    tasks_resp = await auth_client.get("/tasks/")
    done_id = next(t["id"] for t in tasks_resp.json()["tasks"] if t["title"] == "Done task")
    await auth_client.post(f"/tasks/{done_id}/complete")

    view_resp = await auth_client.post(
        "/views/", json={"name": "Active", "filter_config": {"status": ["pending"]}}
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "Pending task"


@pytest.mark.asyncio
async def test_view_filter_tags_include(auth_client: AsyncClient) -> None:
    """tags_include returns only tasks that have ALL listed tags."""
    tag_resp = await auth_client.post("/tags/", json={"name": "type:deep-work"})
    tag_id = tag_resp.json()["id"]
    await auth_client.post("/tasks/", json={"title": "Deep work task", "tag_ids": [tag_id]})
    await auth_client.post("/tasks/", json={"title": "Regular task"})

    view_resp = await auth_client.post(
        "/views/",
        json={"name": "Deep Work", "filter_config": {"tags_include": ["type:deep-work"]}},
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "Deep work task"


@pytest.mark.asyncio
async def test_view_filter_tags_exclude(auth_client: AsyncClient) -> None:
    """tags_exclude excludes tasks that have ANY of the listed tags."""
    tag_resp = await auth_client.post("/tags/", json={"name": "type:meeting"})
    tag_id = tag_resp.json()["id"]
    await auth_client.post("/tasks/", json={"title": "Meeting task", "tag_ids": [tag_id]})
    await auth_client.post("/tasks/", json={"title": "Non-meeting task"})

    view_resp = await auth_client.post(
        "/views/",
        json={"name": "No Meetings", "filter_config": {"tags_exclude": ["type:meeting"]}},
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "Non-meeting task"


@pytest.mark.asyncio
async def test_view_filter_status(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "Task A"})
    tasks_resp = await auth_client.get("/tasks/")
    task_id = tasks_resp.json()["tasks"][0]["id"]
    await auth_client.post(f"/tasks/{task_id}/complete")

    view_resp = await auth_client.post(
        "/views/", json={"name": "Done", "filter_config": {"status": ["done"]}}
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["status"] == "done"


@pytest.mark.asyncio
async def test_view_filter_priority(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "P1 task", "priority": 1})
    await auth_client.post("/tasks/", json={"title": "P3 task", "priority": 3})

    view_resp = await auth_client.post(
        "/views/", json={"name": "High Prio", "filter_config": {"priority": [1, 2]}}
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "P1 task"


@pytest.mark.asyncio
async def test_view_filter_due_within_days(auth_client: AsyncClient) -> None:
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    far = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await auth_client.post("/tasks/", json={"title": "Due soon", "deadline": soon})
    await auth_client.post("/tasks/", json={"title": "Due far", "deadline": far})

    view_resp = await auth_client.post(
        "/views/", json={"name": "This Week", "filter_config": {"due_within_days": 7}}
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "Due soon"


@pytest.mark.asyncio
async def test_view_filter_is_scheduled(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "Unscheduled task"})

    view_resp = await auth_client.post(
        "/views/",
        json={"name": "Unscheduled", "filter_config": {"is_scheduled": False}},
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["scheduled_at"] is None


@pytest.mark.asyncio
async def test_view_filter_project_id(auth_client: AsyncClient) -> None:
    proj_resp = await auth_client.post("/projects/", json={"title": "My Project"})
    proj_id = proj_resp.json()["id"]
    await auth_client.post("/tasks/", json={"title": "Project task", "project_id": proj_id})
    await auth_client.post("/tasks/", json={"title": "Orphan task"})

    view_resp = await auth_client.post(
        "/views/",
        json={"name": "Project View", "filter_config": {"project_id": proj_id}},
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "Project task"


@pytest.mark.asyncio
async def test_view_filter_search(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "Review the PR"})
    await auth_client.post("/tasks/", json={"title": "Write docs"})

    view_resp = await auth_client.post(
        "/views/", json={"name": "Search view", "filter_config": {"search": "review"}}
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert "Review" in data["tasks"][0]["title"]


@pytest.mark.asyncio
async def test_view_sort_config(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "Low P", "priority": 4})
    await auth_client.post("/tasks/", json={"title": "High P", "priority": 1})

    view_resp = await auth_client.post(
        "/views/",
        json={
            "name": "By Priority",
            "filter_config": {},
            "sort_config": {"field": "priority", "direction": "asc"},
        },
    )
    view_id = view_resp.json()["id"]

    response = await auth_client.get(f"/views/{view_id}/tasks")
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert tasks[0]["priority"] == 1
    assert tasks[1]["priority"] == 4


@pytest.mark.asyncio
async def test_get_view_tasks_nonexistent_view_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/views/does_not_exist/tasks")
    assert response.status_code == 404


# ── Update ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_view(auth_client: AsyncClient) -> None:
    create_resp = await auth_client.post(
        "/views/",
        json={"name": "Old Name", "filter_config": {"status": ["pending"]}},
    )
    view_id = create_resp.json()["id"]

    response = await auth_client.patch(
        f"/views/{view_id}",
        json={"name": "New Name", "filter_config": {"status": ["done"]}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["filter_config"] == {"status": ["done"]}


@pytest.mark.asyncio
async def test_update_view_partial(auth_client: AsyncClient) -> None:
    create_resp = await auth_client.post(
        "/views/",
        json={"name": "My View", "filter_config": {"status": ["pending"]}, "position": 3},
    )
    view_id = create_resp.json()["id"]

    response = await auth_client.patch(f"/views/{view_id}", json={"position": 10})
    assert response.status_code == 200
    data = response.json()
    assert data["position"] == 10
    assert data["name"] == "My View"
    assert data["filter_config"] == {"status": ["pending"]}


@pytest.mark.asyncio
async def test_update_nonexistent_view_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.patch("/views/does_not_exist", json={"name": "Updated"})
    assert response.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_view(auth_client: AsyncClient) -> None:
    create_resp = await auth_client.post(
        "/views/", json={"name": "To Delete", "filter_config": {}}
    )
    view_id = create_resp.json()["id"]

    response = await auth_client.delete(f"/views/{view_id}")
    assert response.status_code == 204

    get_resp = await auth_client.get(f"/views/{view_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_view_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.delete("/views/does_not_exist")
    assert response.status_code == 404


# ── Default Views ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_default_views_exist(
    auth_client: AsyncClient, db_session: AsyncSession, test_user: User
) -> None:
    """seed_default_views creates Today, This Week, Unscheduled, High Priority."""
    from kairos.services import view_service

    await view_service.seed_default_views(db_session, test_user)
    await db_session.commit()

    response = await auth_client.get("/views/")
    assert response.status_code == 200
    names = [v["name"] for v in response.json()["views"]]
    assert "Today" in names
    assert "This Week" in names
    assert "Unscheduled" in names
    assert "High Priority" in names


@pytest.mark.asyncio
async def test_seed_default_views_idempotent(
    auth_client: AsyncClient, db_session: AsyncSession, test_user: User
) -> None:
    """Seeding twice doesn't duplicate views."""
    from kairos.services import view_service

    await view_service.seed_default_views(db_session, test_user)
    await db_session.commit()
    await view_service.seed_default_views(db_session, test_user)
    await db_session.commit()

    response = await auth_client.get("/views/")
    names = [v["name"] for v in response.json()["views"]]
    assert names.count("Today") == 1
    assert names.count("This Week") == 1
