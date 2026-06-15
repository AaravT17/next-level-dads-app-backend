from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from typing import Literal
from app.dependencies.auth import get_current_user
from app.models.communities import CommunityResponse
from app.models.users import CommunityMemberResponse
from app.dependencies.db import get_db
import asyncpg
from app.services.communities import (
    build_discover_communities_query,
    build_get_community_by_id_query,
    build_get_community_members_query,
)
from app.models.communities import (
    ConversationCreate,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
    ParticipantResponse,
)
from app.services.communities_service import (
    list_conversations,
    get_conversation,
    list_messages,
    list_participants,
    heart_conversation,
    unheart_conversation,
    heart_message,
    unheart_message,
    start_conversation,
    reply_to_conversation,
    record_to_conversation,
    record_to_message,
    record_to_participant,
)
from uuid import UUID
from datetime import datetime

router = APIRouter(
    prefix="/api/communities",
    tags=["communities"],
)


@router.get("/", response_model=list[CommunityResponse])
async def get_communities(
    name: str | None = None,
    cursor_id: str | None = None,
    cursor_created_at: datetime | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_discover_communities_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=cursor_created_at,
        )
        res = await conn.fetch(query, *params)
        return [CommunityResponse(**dict(r)) for r in res]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch communities. Please try again later.",
        )


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_community(
    name: str = Body(..., max_length=100),
    description: str | None = Body(None, max_length=500),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        async with conn.transaction():
            query = """
                INSERT INTO communities (name, description, created_by, created_at)
                VALUES ($1, $2, $3, NOW())
                RETURNING id
            """
            res = await conn.fetchrow(query, *[name, description, UUID(user_id)])
            if not res:
                raise Exception("Failed to create community.")
            community_id = res["id"]
            query = """
                INSERT INTO community_members (community_id, user_id, role, joined_at)
                VALUES ($1, $2, 'admin', NOW())
            """
            await conn.execute(query, *[community_id, UUID(user_id)])
        return {"id": str(community_id)}
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create community. Please try again later.",
        )


@router.get("/{id}", response_model=CommunityResponse)
async def get_community_by_id(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_get_community_by_id_query(
            id=UUID(id), user_id=UUID(user_id)
        )
        res = await conn.fetchrow(query, *params)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Community not found.",
            )
        return CommunityResponse(**dict(res))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch community details. Please try again later.",
        )


@router.get("/{id}/members", response_model=list[CommunityMemberResponse])
async def get_community_members(
    id: str,
    cursor_id: str | None = Query(None),
    cursor_joined_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_get_community_members_query(
            id=UUID(id),
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_joined_at=cursor_joined_at,
        )
        res = await conn.fetch(query, *params)
        return [CommunityMemberResponse(**dict(r)) for r in res]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch community members. Please try again later.",
        )


@router.post("/{id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def join_community(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        id, user_id = UUID(id), UUID(user_id)
        query = """
            INSERT INTO community_members (community_id, user_id, role, joined_at)
            VALUES ($1, $2, 'member', NOW())
            ON CONFLICT (community_id, user_id) DO NOTHING
        """
        await conn.execute(query, *[id, user_id])
        return
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to join community. Please try again later.",
        )


@router.delete("/{id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def leave_community(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        id, user_id = UUID(id), UUID(user_id)
        query = """
            DELETE FROM community_members
            WHERE community_id = $1 AND user_id = $2
        """
        await conn.execute(query, *[id, user_id])
        return
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to leave community. Please try again later.",
        )


@router.get("/{community_id}/conversations", response_model=list[ConversationResponse])
async def get_community_conversations(
    community_id: str,
    sort: Literal['recent', 'popular', 'active'] = Query('recent'),
    time_window: Literal['today', 'week', 'month', 'year', 'all'] = Query('all'),
    cursor_id: str | None = Query(None),
    cursor_last_activity_at: datetime | None = Query(None),
    cursor_heart_count: int | None = Query(None),
    cursor_reply_count: int | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        records = await list_conversations(
            conn,
            UUID(community_id),
            UUID(user_id),
            sort=sort,
            time_window=time_window,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_last_activity_at=cursor_last_activity_at,
            cursor_heart_count=cursor_heart_count,
            cursor_reply_count=cursor_reply_count,
        )
        return [record_to_conversation(r) for r in records]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch conversations. Please try again later.",
        )


@router.post(
    "/{community_id}/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    community_id: str,
    payload: ConversationCreate,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        return await start_conversation(
            conn,
            UUID(community_id),
            UUID(user_id),
            payload.title,
            payload.body,
            payload.prompt_type,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation. Please try again later.",
        )


# ── Conversation-scoped router ─────────────────────────────────────────────

conversations_router = APIRouter(
    prefix="/api/conversations",
    tags=["conversations"],
)


@conversations_router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_single_conversation(
    conversation_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        record = await get_conversation(conn, UUID(conversation_id), UUID(user_id))
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found.",
            )
        return record_to_conversation(record)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch conversation. Please try again later.",
        )


@conversations_router.get(
    "/{conversation_id}/messages", response_model=list[MessageResponse]
)
async def get_conversation_messages(
    conversation_id: str,
    cursor_id: str | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        records = await list_messages(
            conn,
            UUID(conversation_id),
            UUID(user_id),
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=cursor_created_at,
        )
        return [record_to_message(r) for r in records]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch messages. Please try again later.",
        )


@conversations_router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    conversation_id: str,
    payload: MessageCreate,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        return await reply_to_conversation(
            conn, UUID(conversation_id), UUID(user_id), payload.body
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to post reply. Please try again later.",
        )


@conversations_router.get(
    "/{conversation_id}/participants", response_model=list[ParticipantResponse]
)
async def get_conversation_participants(
    conversation_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        records = await list_participants(conn, UUID(conversation_id))
        return [record_to_participant(r) for r in records]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch participants. Please try again later.",
        )


@conversations_router.post(
    "/{conversation_id}/heart", status_code=status.HTTP_204_NO_CONTENT
)
async def heart_a_conversation(
    conversation_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        await heart_conversation(conn, UUID(conversation_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to heart conversation. Please try again later.",
        )


@conversations_router.delete(
    "/{conversation_id}/heart", status_code=status.HTTP_204_NO_CONTENT
)
async def unheart_a_conversation(
    conversation_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        await unheart_conversation(conn, UUID(conversation_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unheart conversation. Please try again later.",
        )


# ── Message-scoped router ──────────────────────────────────────────────────

messages_router = APIRouter(
    prefix="/api/messages",
    tags=["messages"],
)


@messages_router.post("/{message_id}/heart", status_code=status.HTTP_204_NO_CONTENT)
async def heart_a_message(
    message_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        await heart_message(conn, UUID(message_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to heart message. Please try again later.",
        )


@messages_router.delete("/{message_id}/heart", status_code=status.HTTP_204_NO_CONTENT)
async def unheart_a_message(
    message_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        await unheart_message(conn, UUID(message_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unheart message. Please try again later.",
        )
