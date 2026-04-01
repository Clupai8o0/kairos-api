"""Business logic for chat session persistence."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.models.chat_session import ChatSession
from kairos.models.user import User
from kairos.schemas.chat import ChatSessionCreate, ChatSessionUpdate


def _preview(messages: list[dict], max_len: int = 80) -> str:
    """Return a short preview string from the first user message."""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                # content_part[] — join text parts
                text = " ".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
            else:
                text = str(content)
            return text[:max_len] + ("…" if len(text) > max_len else "")
    return ""


async def create_session(
    db: AsyncSession,
    user: User,
    data: ChatSessionCreate,
) -> ChatSession:
    messages_as_dicts = [m.model_dump() for m in data.messages]
    session = ChatSession(
        user_id=user.id,
        messages=messages_as_dicts,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def list_sessions(
    db: AsyncSession,
    user: User,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ChatSession], int]:
    count_q = select(func.count()).select_from(ChatSession).where(
        ChatSession.user_id == user.id
    )
    total = (await db.execute(count_q)).scalar_one()

    rows = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars().all()), total


async def get_session(
    db: AsyncSession,
    user: User,
    session_id: str,
) -> ChatSession | None:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    return result.scalar_one_or_none()


async def update_session(
    db: AsyncSession,
    user: User,
    session_id: str,
    data: ChatSessionUpdate,
) -> ChatSession | None:
    session = await get_session(db, user, session_id)
    if session is None:
        return None
    session.messages = [m.model_dump() for m in data.messages]
    await db.flush()
    await db.refresh(session)
    return session


async def delete_session(
    db: AsyncSession,
    user: User,
    session_id: str,
) -> bool:
    session = await get_session(db, user, session_id)
    if session is None:
        return False
    await db.delete(session)
    await db.flush()
    return True
