"""Tests for the chat sessions API."""

import pytest
from httpx import AsyncClient


# ── Helpers ───────────────────────────────────────────────────────────────────

MESSAGES = [
    {"role": "user", "content": "Schedule my afternoon"},
    {"role": "assistant", "content": "I've scheduled 3 tasks for you."},
]


# ── Create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_session_returns_201(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/chat/sessions", json={"messages": MESSAGES})
    assert response.status_code == 201
    data = response.json()
    assert "session_id" in data
    assert data["message_count"] == 2
    assert data["messages"] == MESSAGES


@pytest.mark.asyncio
async def test_create_session_empty_messages_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/chat/sessions", json={"messages": []})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_session_no_messages_field_returns_422(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/chat/sessions", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_session_response_shape(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/chat/sessions", json={"messages": MESSAGES})
    data = response.json()
    assert "session_id" in data
    assert "messages" in data
    assert "message_count" in data
    assert "created_at" in data
    assert "updated_at" in data


# ── List ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_sessions_empty(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/chat/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["sessions"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_sessions_returns_summaries(auth_client: AsyncClient) -> None:
    await auth_client.post("/chat/sessions", json={"messages": MESSAGES})
    await auth_client.post("/chat/sessions", json={"messages": MESSAGES})

    response = await auth_client.get("/chat/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["sessions"]) == 2


@pytest.mark.asyncio
async def test_list_sessions_summary_has_no_messages_field(auth_client: AsyncClient) -> None:
    """List response returns summaries (no full message array)."""
    await auth_client.post("/chat/sessions", json={"messages": MESSAGES})

    response = await auth_client.get("/chat/sessions")
    session = response.json()["sessions"][0]
    assert "messages" not in session
    assert "preview" in session
    assert "message_count" in session
    assert "session_id" in session


@pytest.mark.asyncio
async def test_list_sessions_preview_from_first_user_message(auth_client: AsyncClient) -> None:
    await auth_client.post("/chat/sessions", json={"messages": MESSAGES})

    response = await auth_client.get("/chat/sessions")
    preview = response.json()["sessions"][0]["preview"]
    assert "Schedule my afternoon" in preview


@pytest.mark.asyncio
async def test_list_sessions_pagination(auth_client: AsyncClient) -> None:
    for _ in range(5):
        await auth_client.post("/chat/sessions", json={"messages": MESSAGES})

    response = await auth_client.get("/chat/sessions?limit=2&offset=0")
    data = response.json()
    assert len(data["sessions"]) == 2
    assert data["total"] == 5


# ── Get ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_session_by_id(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/chat/sessions", json={"messages": MESSAGES})
    session_id = create.json()["session_id"]

    response = await auth_client.get(f"/chat/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == session_id
    assert data["messages"] == MESSAGES


@pytest.mark.asyncio
async def test_get_nonexistent_session_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/chat/sessions/nonexistent_id")
    assert response.status_code == 404


# ── Update ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_session_replaces_messages(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/chat/sessions", json={"messages": MESSAGES})
    session_id = create.json()["session_id"]

    new_messages = [
        {"role": "user", "content": "Never mind"},
        {"role": "assistant", "content": "OK, cleared."},
        {"role": "user", "content": "Start fresh"},
    ]
    response = await auth_client.put(
        f"/chat/sessions/{session_id}", json={"messages": new_messages}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["messages"] == new_messages
    assert data["message_count"] == 3


@pytest.mark.asyncio
async def test_update_nonexistent_session_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.put(
        "/chat/sessions/nonexistent_id", json={"messages": MESSAGES}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_session_empty_messages_returns_422(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/chat/sessions", json={"messages": MESSAGES})
    session_id = create.json()["session_id"]

    response = await auth_client.put(
        f"/chat/sessions/{session_id}", json={"messages": []}
    )
    assert response.status_code == 422


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_session(auth_client: AsyncClient) -> None:
    create = await auth_client.post("/chat/sessions", json={"messages": MESSAGES})
    session_id = create.json()["session_id"]

    response = await auth_client.delete(f"/chat/sessions/{session_id}")
    assert response.status_code == 204

    get_response = await auth_client.get(f"/chat/sessions/{session_id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_session_returns_404(auth_client: AsyncClient) -> None:
    response = await auth_client.delete("/chat/sessions/nonexistent_id")
    assert response.status_code == 404


# ── Auth ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthenticated_requests_return_401(unauthed_client) -> None:
    endpoints = [
        ("POST", "/chat/sessions", {"messages": MESSAGES}),
        ("GET", "/chat/sessions", None),
        ("GET", "/chat/sessions/some_id", None),
        ("PUT", "/chat/sessions/some_id", {"messages": MESSAGES}),
        ("DELETE", "/chat/sessions/some_id", None),
    ]
    for method, path, body in endpoints:
        if body:
            response = await unauthed_client.request(method, path, json=body)
        else:
            response = await unauthed_client.request(method, path)
        assert response.status_code == 401, f"{method} {path} expected 401"


# ── Content types ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_session_with_list_content_parts(auth_client: AsyncClient) -> None:
    """Messages with content_part[] arrays should be stored and returned correctly."""
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "Show my tasks"}],
        },
        {"role": "assistant", "content": "Here are your tasks."},
    ]
    response = await auth_client.post("/chat/sessions", json={"messages": messages})
    assert response.status_code == 201
    assert response.json()["messages"] == messages
