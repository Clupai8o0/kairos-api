import pytest
from httpx import AsyncClient


# ── Auth guards ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tags_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get("/tags/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_tag_requires_auth(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.post("/tags/", json={"name": "area:work"})
    assert response.status_code == 401


# ── Create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_tag(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/tags/", json={"name": "area:work", "color": "#2563EB", "icon": "briefcase"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "area:work"
    assert data["color"] == "#2563EB"
    assert data["icon"] == "briefcase"
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_tag_minimal(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/tags/", json={"name": "context:laptop"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "context:laptop"
    assert data["color"] is None
    assert data["icon"] is None


@pytest.mark.asyncio
async def test_create_duplicate_tag_returns_409(auth_client: AsyncClient) -> None:
    await auth_client.post("/tags/", json={"name": "area:work"})
    response = await auth_client.post("/tags/", json={"name": "area:work"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_tag_empty_name_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/tags/", json={"name": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_tag_name_too_long_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/tags/", json={"name": "x" * 101})
    assert response.status_code == 422


# ── List ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tags_empty(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/tags/")
    assert response.status_code == 200
    data = response.json()
    assert data["tags"] == []


@pytest.mark.asyncio
async def test_list_tags_with_counts(auth_client: AsyncClient) -> None:
    await auth_client.post("/tags/", json={"name": "area:work", "color": "#2563EB"})
    await auth_client.post("/tags/", json={"name": "type:deep-work"})

    response = await auth_client.get("/tags/")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tags"]) == 2

    for tag in data["tags"]:
        assert "task_count" in tag
        assert "project_count" in tag
        assert tag["task_count"] == 0
        assert tag["project_count"] == 0


@pytest.mark.asyncio
async def test_list_tags_sorted_by_name(auth_client: AsyncClient) -> None:
    await auth_client.post("/tags/", json={"name": "zzz"})
    await auth_client.post("/tags/", json={"name": "aaa"})

    response = await auth_client.get("/tags/")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()["tags"]]
    assert names == sorted(names)


# ── Update ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_tag(auth_client: AsyncClient) -> None:
    create_resp = await auth_client.post(
        "/tags/", json={"name": "area:work", "color": "#000000"}
    )
    tag_id = create_resp.json()["id"]

    response = await auth_client.patch(
        f"/tags/{tag_id}", json={"name": "area:work-updated", "color": "#FFFFFF"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "area:work-updated"
    assert data["color"] == "#FFFFFF"


@pytest.mark.asyncio
async def test_update_tag_partial(auth_client: AsyncClient) -> None:
    create_resp = await auth_client.post(
        "/tags/", json={"name": "area:work", "color": "#000000", "icon": "briefcase"}
    )
    tag_id = create_resp.json()["id"]

    response = await auth_client.patch(f"/tags/{tag_id}", json={"color": "#FF5500"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "area:work"   # unchanged
    assert data["icon"] == "briefcase"   # unchanged
    assert data["color"] == "#FF5500"


@pytest.mark.asyncio
async def test_update_nonexistent_tag_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.patch("/tags/does_not_exist", json={"color": "#FF0000"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_tag_duplicate_name_returns_409(auth_client: AsyncClient) -> None:
    await auth_client.post("/tags/", json={"name": "tag-a"})
    resp_b = await auth_client.post("/tags/", json={"name": "tag-b"})
    tag_b_id = resp_b.json()["id"]

    response = await auth_client.patch(f"/tags/{tag_b_id}", json={"name": "tag-a"})
    assert response.status_code == 409


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_tag(auth_client: AsyncClient) -> None:
    create_resp = await auth_client.post("/tags/", json={"name": "area:work"})
    tag_id = create_resp.json()["id"]

    response = await auth_client.delete(f"/tags/{tag_id}")
    assert response.status_code == 204

    # Confirm tag is gone from list
    list_resp = await auth_client.get("/tags/")
    names = [t["name"] for t in list_resp.json()["tags"]]
    assert "area:work" not in names


@pytest.mark.asyncio
async def test_delete_nonexistent_tag_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.delete("/tags/does_not_exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_tag_removes_task_association(auth_client: AsyncClient) -> None:
    tag_resp = await auth_client.post("/tags/", json={"name": "area:work"})
    tag_id = tag_resp.json()["id"]

    task_resp = await auth_client.post(
        "/tasks/", json={"title": "A task", "tag_ids": [tag_id]}
    )
    task_id = task_resp.json()["id"]

    await auth_client.delete(f"/tags/{tag_id}")

    task_resp = await auth_client.get(f"/tasks/{task_id}")
    assert task_resp.status_code == 200
    assert task_resp.json()["tags"] == []
