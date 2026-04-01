from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.core.auth import get_current_user
from kairos.core.deps import get_db
from kairos.models.user import User
from kairos.schemas.chat import (
    ChatSessionCreate,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatSessionSummary,
    ChatSessionUpdate,
)
from kairos.services import chat_service
from kairos.services.chat_service import _preview

router = APIRouter()


def _to_response(session) -> ChatSessionResponse:
    return ChatSessionResponse(
        session_id=session.id,
        messages=session.messages,
        message_count=len(session.messages),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _to_summary(session) -> ChatSessionSummary:
    return ChatSessionSummary(
        session_id=session.id,
        message_count=len(session.messages),
        preview=_preview(session.messages),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.post("/sessions", response_model=ChatSessionResponse, status_code=201)
async def create_session(
    data: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionResponse:
    """Persist a new chat session with its full message history."""
    session = await chat_service.create_session(db, current_user, data)
    return _to_response(session)


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionListResponse:
    """List chat sessions for the current user, newest first."""
    sessions, total = await chat_service.list_sessions(
        db, current_user, limit=limit, offset=offset
    )
    return ChatSessionListResponse(
        sessions=[_to_summary(s) for s in sessions],
        total=total,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionResponse:
    """Retrieve a single chat session with all messages."""
    session = await chat_service.get_session(db, current_user, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return _to_response(session)


@router.put("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    session_id: str,
    data: ChatSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionResponse:
    """Replace the messages in an existing session."""
    session = await chat_service.update_session(db, current_user, session_id, data)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return _to_response(session)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a chat session."""
    deleted = await chat_service.delete_session(db, current_user, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found")
