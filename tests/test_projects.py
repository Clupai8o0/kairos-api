import pytest
from httpx import AsyncClient


# ── Auth guard ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_projects_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get("/projects/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_project_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.post("/projects/", json={"title": "x"})
    assert response.status_code == 401


# ── CRUD — Happy Path ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_project_minimal(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/projects/", json={"title": "Kairos Backend"})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Kairos Backend"
    assert data["status"] == "active"
    assert data["tags"] == []
    assert data["metadata"] == {}
    assert "id" in data


@pytest.mark.asyncio
async def test_create_project_all_fields(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/projects/",
        json={
            "title": "Full Project",
            "description": "A fully specified project",
            "deadline": "2026-06-01T00:00:00Z",
            "color": "#10B981",
            "metadata": {"source": "notion"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Full Project"
    assert data["description"] == "A fully specified project"
    assert data["color"] == "#10B981"
    assert data["metadata"] == {"source": "notion"}


@pytest.mark.asyncio
async def test_list_projects_empty(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/projects/")
    assert response.status_code == 200
    data = response.json()
    assert data["projects"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_projects_returns_all(auth_client: AsyncClient) -> None:
    for i in range(3):
        await auth_client.post("/projects/", json={"title": f"Project {i}"})
    response = await auth_client.get("/projects/")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["projects"]) == 3


@pytest.mark.asyncio
async def test_get_project_by_id(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/projects/", json={"title": "Fetch me"})
    project_id = create.json()["id"]
    response = await auth_client.get(f"/projects/{project_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project_id
    assert data["title"] == "Fetch me"
    assert "tasks" in data  # ProjectWithTasksResponse includes nested tasks


@pytest.mark.asyncio
async def test_update_project_partial(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/projects/", json={"title": "Old title"})
    project_id = create.json()["id"]
    response = await auth_client.patch(
        f"/projects/{project_id}", json={"title": "New title"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "New title"


@pytest.mark.asyncio
async def test_update_project_multiple_fields(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/projects/", json={"title": "Project Alpha"})
    project_id = create.json()["id"]
    response = await auth_client.patch(
        f"/projects/{project_id}",
        json={"title": "Project Beta", "description": "Updated", "color": "#FF0000"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Project Beta"
    assert data["description"] == "Updated"
    assert data["color"] == "#FF0000"


@pytest.mark.asyncio
async def test_update_project_status(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/projects/", json={"title": "In progress project"})
    project_id = create.json()["id"]
    response = await auth_client.patch(
        f"/projects/{project_id}", json={"status": "paused"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "paused"


@pytest.mark.asyncio
async def test_delete_project_soft(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/projects/", json={"title": "Archive me"})
    project_id = create.json()["id"]
    response = await auth_client.delete(f"/projects/{project_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_delete_project_tasks_lose_association(auth_client: AsyncClient) -> None:
    """Deleting a project must unlink its tasks (project_id → null), not delete them."""
    proj = await auth_client.post("/projects/", json={"title": "Project to delete"})
    project_id = proj.json()["id"]

    task = await auth_client.post(
        "/tasks/", json={"title": "Orphan task", "project_id": project_id}
    )
    task_id = task.json()["id"]

    await auth_client.delete(f"/projects/{project_id}")

    # Task still exists, no longer associated with the project
    task_resp = await auth_client.get(f"/tasks/{task_id}")
    assert task_resp.status_code == 200
    assert task_resp.json()["project_id"] is None


# ── Filtering ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_projects_filter_by_status(auth_client: AsyncClient) -> None:
    await auth_client.post("/projects/", json={"title": "Active project"})
    create = await auth_client.post("/projects/", json={"title": "Paused project"})
    project_id = create.json()["id"]
    await auth_client.patch(f"/projects/{project_id}", json={"status": "paused"})

    response = await auth_client.get("/projects/?status=paused")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["projects"][0]["status"] == "paused"


@pytest.mark.asyncio
async def test_list_projects_search(auth_client: AsyncClient) -> None:
    await auth_client.post("/projects/", json={"title": "Kairos Backend"})
    await auth_client.post("/projects/", json={"title": "Frontend App"})

    response = await auth_client.get("/projects/?search=kairos")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["projects"][0]["title"] == "Kairos Backend"


# ── Project tasks sub-resource ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_project_tasks_empty(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/projects/", json={"title": "Empty project"})
    project_id = create.json()["id"]
    response = await auth_client.get(f"/projects/{project_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["tasks"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_project_tasks_returns_tasks(auth_client: AsyncClient) -> None:
    proj = await auth_client.post("/projects/", json={"title": "Active project"})
    project_id = proj.json()["id"]

    for i in range(2):
        await auth_client.post(
            "/tasks/", json={"title": f"Task {i}", "project_id": project_id}
        )
    # Task outside the project — should NOT appear
    await auth_client.post("/tasks/", json={"title": "Unrelated task"})

    response = await auth_client.get(f"/projects/{project_id}/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert all(t["project_id"] == project_id for t in data["tasks"])


# ── Error Cases ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_project_no_title_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/projects/", json={"color": "#111111"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_nonexistent_project_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/projects/nonexistent_id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_nonexistent_project_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.patch("/projects/nonexistent_id", json={"title": "x"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_project_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.delete("/projects/nonexistent_id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_project_tasks_nonexistent_project_returns_404(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.get("/projects/nonexistent_id/tasks")
    assert response.status_code == 404

