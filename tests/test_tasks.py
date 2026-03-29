import pytest
from httpx import AsyncClient


# ── CRUD — Happy Path ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_task_minimal(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/tasks/", json={"title": "Buy milk"})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Buy milk"
    assert data["status"] == "pending"
    assert data["priority"] == 3
    assert data["tags"] == []
    assert "id" in data


@pytest.mark.asyncio
async def test_create_task_all_fields(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/tasks/",
        json={
            "title": "Review PR #42",
            "description": "Check the auth refactor",
            "duration_mins": 30,
            "deadline": "2026-04-01T17:00:00Z",
            "priority": 2,
            "is_splittable": False,
            "depends_on": [],
            "schedulable": True,
            "buffer_mins": 15,
            "metadata": {"source": "jira"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Review PR #42"
    assert data["duration_mins"] == 30
    assert data["priority"] == 2
    assert data["metadata"] == {"source": "jira"}


@pytest.mark.asyncio
async def test_list_tasks_empty(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/tasks/")
    assert response.status_code == 200
    data = response.json()
    assert data["tasks"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_tasks_returns_all(auth_client: AsyncClient) -> None:
    for i in range(3):
        await auth_client.post("/tasks/", json={"title": f"Task {i}"})
    response = await auth_client.get("/tasks/")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["tasks"]) == 3


@pytest.mark.asyncio
async def test_get_task_by_id(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/tasks/", json={"title": "Fetch me"})
    task_id = create.json()["id"]
    response = await auth_client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["id"] == task_id
    assert response.json()["title"] == "Fetch me"


@pytest.mark.asyncio
async def test_update_task_partial(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/tasks/", json={"title": "Old title"})
    task_id = create.json()["id"]
    response = await auth_client.patch(f"/tasks/{task_id}", json={"title": "New title"})
    assert response.status_code == 200
    assert response.json()["title"] == "New title"


@pytest.mark.asyncio
async def test_update_task_multiple_fields(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/tasks/", json={"title": "Task", "priority": 3})
    task_id = create.json()["id"]
    response = await auth_client.patch(
        f"/tasks/{task_id}",
        json={"title": "Updated Task", "priority": 1, "description": "Added desc"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Task"
    assert data["priority"] == 1
    assert data["description"] == "Added desc"


@pytest.mark.asyncio
async def test_delete_task_soft(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/tasks/", json={"title": "Delete me"})
    task_id = create.json()["id"]
    response = await auth_client.delete(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_complete_task(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/tasks/", json={"title": "Finish me"})
    task_id = create.json()["id"]
    response = await auth_client.post(f"/tasks/{task_id}/complete")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "done"
    assert data["completed_at"] is not None


@pytest.mark.asyncio
async def test_unschedule_task(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/tasks/", json={"title": "Unschedule me"})
    task_id = create.json()["id"]
    response = await auth_client.post(f"/tasks/{task_id}/unschedule")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["scheduled_at"] is None


# ── CRUD — Error Cases ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_task_no_title_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/tasks/", json={"priority": 2})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_nonexistent_task_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/tasks/nonexistent_id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_nonexistent_task_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.patch("/tasks/nonexistent_id", json={"title": "x"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_task_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.delete("/tasks/nonexistent_id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_task_invalid_priority_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/tasks/", json={"title": "Task", "priority": 5})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_task_negative_duration_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/tasks/", json={"title": "Task", "duration_mins": -5})
    assert response.status_code == 422


# ── Filtering ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_filter_tasks_by_status(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "Pending task"})
    done_create = await auth_client.post("/tasks/", json={"title": "Done task"})
    await auth_client.post(f"/tasks/{done_create.json()['id']}/complete")

    response = await auth_client.get("/tasks/?status=pending")
    data = response.json()
    assert response.status_code == 200
    assert all(t["status"] == "pending" for t in data["tasks"])
    assert any(t["title"] == "Pending task" for t in data["tasks"])


@pytest.mark.asyncio
async def test_filter_tasks_by_priority(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "P1 task", "priority": 1})
    await auth_client.post("/tasks/", json={"title": "P3 task", "priority": 3})

    response = await auth_client.get("/tasks/?priority=1")
    data = response.json()
    assert response.status_code == 200
    assert all(t["priority"] == 1 for t in data["tasks"])
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_filter_tasks_by_scheduled(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "Unscheduled task"})

    response = await auth_client.get("/tasks/?is_scheduled=false")
    data = response.json()
    assert response.status_code == 200
    assert all(t["scheduled_at"] is None for t in data["tasks"])


@pytest.mark.asyncio
async def test_filter_tasks_by_deadline(auth_client: AsyncClient) -> None:
    await auth_client.post(
        "/tasks/", json={"title": "Due soon", "deadline": "2026-04-01T00:00:00Z"}
    )
    await auth_client.post(
        "/tasks/", json={"title": "Due later", "deadline": "2026-06-01T00:00:00Z"}
    )

    response = await auth_client.get("/tasks/?due_before=2026-05-01T00:00:00Z")
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "Due soon"


@pytest.mark.asyncio
async def test_filter_tasks_combined(auth_client: AsyncClient) -> None:
    await auth_client.post(
        "/tasks/",
        json={"title": "P1 soon", "priority": 1, "deadline": "2026-04-01T00:00:00Z"},
    )
    await auth_client.post(
        "/tasks/",
        json={"title": "P3 soon", "priority": 3, "deadline": "2026-04-01T00:00:00Z"},
    )
    await auth_client.post("/tasks/", json={"title": "P1 no deadline", "priority": 1})

    response = await auth_client.get(
        "/tasks/?priority=1&due_before=2026-05-01T00:00:00Z"
    )
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "P1 soon"


@pytest.mark.asyncio
async def test_search_tasks_by_keyword(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "Review the PR"})
    await auth_client.post("/tasks/", json={"title": "Buy groceries"})

    response = await auth_client.get("/tasks/?search=review")
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "Review the PR"


@pytest.mark.asyncio
async def test_sort_tasks_by_priority(auth_client: AsyncClient) -> None:
    await auth_client.post("/tasks/", json={"title": "P3", "priority": 3})
    await auth_client.post("/tasks/", json={"title": "P1", "priority": 1})
    await auth_client.post("/tasks/", json={"title": "P2", "priority": 2})

    response = await auth_client.get("/tasks/?sort=priority&order=asc")
    data = response.json()
    priorities = [t["priority"] for t in data["tasks"]]
    assert priorities == sorted(priorities)


@pytest.mark.asyncio
async def test_pagination_limit_offset(auth_client: AsyncClient) -> None:
    for i in range(5):
        await auth_client.post("/tasks/", json={"title": f"Task {i}"})

    response = await auth_client.get("/tasks/?limit=2&offset=2&sort=created_at&order=asc")
    data = response.json()
    assert len(data["tasks"]) == 2
    assert data["total"] == 5


# ── Tags on Tasks ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_task_with_tags(
    auth_client: AsyncClient, db_session, test_user
) -> None:
    from kairos.models.tag import Tag

    tag = Tag(id="tag_work_1", user_id=test_user.id, name="area:work", color="#2563EB")
    db_session.add(tag)
    await db_session.flush()

    response = await auth_client.post(
        "/tasks/", json={"title": "Tagged task", "tag_ids": ["tag_work_1"]}
    )
    assert response.status_code == 201
    data = response.json()
    assert len(data["tags"]) == 1
    assert data["tags"][0]["name"] == "area:work"


@pytest.mark.asyncio
async def test_update_task_tags(
    auth_client: AsyncClient, db_session, test_user
) -> None:
    from kairos.models.tag import Tag

    tag_a = Tag(id="tag_a", user_id=test_user.id, name="area:work")
    tag_b = Tag(id="tag_b", user_id=test_user.id, name="context:laptop")
    db_session.add(tag_a)
    db_session.add(tag_b)
    await db_session.flush()

    create = await auth_client.post(
        "/tasks/", json={"title": "Task", "tag_ids": ["tag_a"]}
    )
    task_id = create.json()["id"]
    assert create.json()["tags"][0]["name"] == "area:work"

    response = await auth_client.patch(f"/tasks/{task_id}", json={"tag_ids": ["tag_b"]})
    assert response.status_code == 200
    data = response.json()
    assert len(data["tags"]) == 1
    assert data["tags"][0]["name"] == "context:laptop"


@pytest.mark.asyncio
async def test_task_response_includes_tags(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/tasks/", json={"title": "No tags task"})
    task_id = create.json()["id"]
    response = await auth_client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert "tags" in data
    assert isinstance(data["tags"], list)


# ── Dependencies ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_task_with_depends_on(auth_client: AsyncClient) -> None:
    dep = await auth_client.post("/tasks/", json={"title": "Dependency"})
    dep_id = dep.json()["id"]

    response = await auth_client.post(
        "/tasks/", json={"title": "Dependent task", "depends_on": [dep_id]}
    )
    assert response.status_code == 201
    assert dep_id in response.json()["depends_on"]


@pytest.mark.asyncio
async def test_depends_on_nonexistent_task(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/tasks/", json={"title": "Task", "depends_on": ["fake_dep_id"]}
    )
    assert response.status_code == 201
    assert "fake_dep_id" in response.json()["depends_on"]
