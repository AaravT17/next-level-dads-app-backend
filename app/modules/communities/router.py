from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from app.common.config.constants import IS_PRODUCTION
from app.common.dependencies.rate_limiting import (
    CreateCommunityLimiter,
    CreateConversationLimiter,
    InviteToCommunityLimiter,
    PostMessageLimiter,
    PostReplyLimiter,
    UpdateCommunityImageLimiter,
)
from typing import Literal
from app.common.dependencies.auth import get_consented_user
from app.modules.communities.models import CommunityResponse
from app.modules.users.models import CommunityMemberResponse
from app.common.dependencies.db import get_db, get_pool
from app.modules.moderation.models import ContentType
from app.modules.moderation.service import assert_not_banned, moderate_content
import asyncpg
import app.modules.communities.service as communities_service
from app.modules.communities.models import (
    CommunityInviteRequest,
    CommunityInviteResponse,
    ConversationCreate,
    ConversationResponse,
    FeedConversationResponse,
    MessageCreate,
    MessageResponse,
    ParticipantResponse,
    ReplyCreate,
    ReplyResponse,
)
from uuid import UUID
from datetime import datetime

router = APIRouter(
    prefix='/api/communities',
    tags=['communities'],
)


@router.get('/', response_model=list[CommunityResponse])
async def discover_communities(
    name: str | None = None,
    cursor_id: str | None = None,
    cursor_created_at: datetime | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    return await communities_service.discover_communities(conn, user_id, name, cursor_id, cursor_created_at)


@router.post(
    '/',
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_consented_user), Depends(CreateCommunityLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def create_community(
    request: Request,
    name: str = Body(..., max_length=100),
    description: str | None = Body(None, max_length=500),
    conn: asyncpg.Connection = Depends(get_db),
):
    community_id = await communities_service.create_community(conn, request.state.user_id, name, description)
    return {'id': community_id}


@router.get('/{id}', response_model=CommunityResponse)
async def get_community(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    return await communities_service.get_community(conn, id, user_id)


@router.get('/{id}/members', response_model=list[CommunityMemberResponse])
async def get_community_members(
    id: str,
    cursor_id: str | None = Query(None),
    cursor_joined_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    return await communities_service.get_community_members(conn, id, cursor_id, cursor_joined_at)


@router.post('/{id}/members', status_code=status.HTTP_204_NO_CONTENT)
async def join_community(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    await communities_service.join_community(conn, id, user_id)


@router.delete('/{id}/members', status_code=status.HTTP_204_NO_CONTENT)
async def leave_community(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    await communities_service.leave_community(conn, id, user_id)


@router.put(
    '/{id}/image',
    dependencies=[Depends(get_consented_user), Depends(UpdateCommunityImageLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def update_community_image(
    id: str,
    request: Request,
    image: UploadFile = File(...),
    conn: asyncpg.Connection = Depends(get_db),
):
    file_contents = await image.read()
    image_url = await communities_service.update_community_image(
        conn, id, request.state.user_id, file_contents, image.content_type
    )
    return {'image_url': image_url}


@router.delete('/{id}/image', status_code=status.HTTP_204_NO_CONTENT)
async def delete_community_image(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    await communities_service.delete_community_image(conn, id, user_id)


@router.post(
    '/{id}/invites',
    response_model=CommunityInviteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_consented_user), Depends(InviteToCommunityLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def invite_to_community(
    id: str,
    body: CommunityInviteRequest,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        community_id = UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid community id.')

    invited_count = await communities_service.invite_to_community(
        conn,
        UUID(request.state.user_id),
        community_id,
        body.recipient_ids,
    )
    return CommunityInviteResponse(invited_count=invited_count)


@router.get('/{community_id}/conversations', response_model=list[ConversationResponse])
async def get_community_conversations(
    community_id: str,
    sort: Literal['recent', 'popular', 'active'] = Query('recent'),
    time_window: Literal['today', 'week', 'month', 'year', 'all'] = Query('all'),
    cursor_id: str | None = Query(None),
    cursor_last_activity_at: datetime | None = Query(None),
    cursor_heart_count: int | None = Query(None),
    cursor_reply_count: int | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        records = await communities_service.list_conversations(
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
        return [communities_service.record_to_conversation(r) for r in records]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch conversations. Please try again later.',
        )


@router.post(
    '/{community_id}/conversations',
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_consented_user), Depends(CreateConversationLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def create_conversation(
    community_id: str,
    payload: ConversationCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
    pool: asyncpg.Pool = Depends(get_pool),
):
    try:
        uid = UUID(request.state.user_id)
        cid = UUID(community_id)
        await assert_not_banned(conn, uid)
        conversation = await communities_service.start_conversation(
            conn, cid, uid, payload.title, payload.body, payload.prompt_type
        )
        background_tasks.add_task(
            moderate_content,
            pool,
            ContentType.CONVERSATION,
            conversation.id,
            uid,
            cid,
            f'{payload.title}\n{payload.body}',
        )
        return conversation
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to create conversation. Please try again later.',
        )


# ── Conversation-scoped router ─────────────────────────────────────────────

conversations_router = APIRouter(
    prefix='/api/conversations',
    tags=['conversations'],
)


@conversations_router.get('', response_model=list[FeedConversationResponse])
async def get_conversations_feed(
    following: bool = Query(False),
    cursor_id: str | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        records = await communities_service.list_feed_conversations(
            conn,
            UUID(user_id),
            following=following,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=cursor_created_at,
        )
        return [communities_service.record_to_feed_conversation(r) for r in records]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch conversations. Please try again later.',
        )


@conversations_router.get('/{conversation_id}', response_model=ConversationResponse)
async def get_single_conversation(
    conversation_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        record = await communities_service.get_conversation(conn, UUID(conversation_id), UUID(user_id))
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Conversation not found.',
            )
        return communities_service.record_to_conversation(record)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch conversation. Please try again later.',
        )


@conversations_router.delete('/{conversation_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_a_conversation(
    conversation_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        await communities_service.delete_conversation(conn, UUID(conversation_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to delete conversation. Please try again later.',
        )


@conversations_router.get('/{conversation_id}/messages', response_model=list[MessageResponse])
async def get_conversation_messages(
    conversation_id: str,
    cursor_id: str | None = Query(None),
    cursor_created_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        records = await communities_service.list_messages(
            conn,
            UUID(conversation_id),
            UUID(user_id),
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=cursor_created_at,
        )
        return [communities_service.record_to_message(r) for r in records]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch messages. Please try again later.',
        )


@conversations_router.post(
    '/{conversation_id}/messages',
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_consented_user), Depends(PostMessageLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def create_message(
    conversation_id: str,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
    pool: asyncpg.Pool = Depends(get_pool),
):
    try:
        uid = UUID(request.state.user_id)
        await assert_not_banned(conn, uid)
        message = await communities_service.reply_to_conversation(conn, UUID(conversation_id), uid, payload.body)
        background_tasks.add_task(
            moderate_content,
            pool,
            ContentType.MESSAGE,
            message.id,
            uid,
            None,
            payload.body,
        )
        return message
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to post reply. Please try again later.',
        )


@conversations_router.get('/{conversation_id}/participants', response_model=list[ParticipantResponse])
async def get_conversation_participants(
    conversation_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        records = await communities_service.list_participants(conn, UUID(conversation_id))
        return [communities_service.record_to_participant(r) for r in records]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch participants. Please try again later.',
        )


@conversations_router.post('/{conversation_id}/heart', status_code=status.HTTP_204_NO_CONTENT)
async def heart_a_conversation(
    conversation_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        uid = UUID(user_id)
        await assert_not_banned(conn, uid)
        await communities_service.heart_conversation(conn, UUID(conversation_id), uid)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to heart conversation. Please try again later.',
        )


@conversations_router.delete('/{conversation_id}/heart', status_code=status.HTTP_204_NO_CONTENT)
async def unheart_a_conversation(
    conversation_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        await communities_service.unheart_conversation(conn, UUID(conversation_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to unheart conversation. Please try again later.',
        )


# ── Message-scoped router ──────────────────────────────────────────────────

messages_router = APIRouter(
    prefix='/api/messages',
    tags=['messages'],
)


@messages_router.post('/{message_id}/heart', status_code=status.HTTP_204_NO_CONTENT)
async def heart_a_message(
    message_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        uid = UUID(user_id)
        await assert_not_banned(conn, uid)
        await communities_service.heart_message(conn, UUID(message_id), uid)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to heart message. Please try again later.',
        )


@messages_router.delete('/{message_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_a_message(
    message_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        await communities_service.delete_message(conn, UUID(message_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to delete message. Please try again later.',
        )


@messages_router.delete('/{message_id}/heart', status_code=status.HTTP_204_NO_CONTENT)
async def unheart_a_message(
    message_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        await communities_service.unheart_message(conn, UUID(message_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to unheart message. Please try again later.',
        )


@messages_router.get('/{message_id}/replies', response_model=list[ReplyResponse])
async def get_message_replies(
    message_id: str,
    cursor_id: str | None = Query(None),
    cursor_heart_count: int | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        records = await communities_service.list_replies(
            conn,
            UUID(message_id),
            UUID(user_id),
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_heart_count=cursor_heart_count,
        )
        return [communities_service.record_to_reply(r) for r in records]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch replies. Please try again later.',
        )


@messages_router.post(
    '/{message_id}/replies',
    response_model=ReplyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_consented_user), Depends(PostReplyLimiter())]
    if IS_PRODUCTION
    else [Depends(get_consented_user)],
)
async def create_reply(
    message_id: str,
    payload: ReplyCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
    pool: asyncpg.Pool = Depends(get_pool),
):
    try:
        uid = UUID(request.state.user_id)
        await assert_not_banned(conn, uid)
        reply = await communities_service.reply_to_message(conn, UUID(message_id), uid, payload.body)
        background_tasks.add_task(
            moderate_content,
            pool,
            ContentType.REPLY,
            reply.id,
            uid,
            None,
            payload.body,
        )
        return reply
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to post reply. Please try again later.',
        )


# ── Reply-scoped router ────────────────────────────────────────────────────

replies_router = APIRouter(
    prefix='/api/replies',
    tags=['replies'],
)


@replies_router.post('/{reply_id}/heart', status_code=status.HTTP_204_NO_CONTENT)
async def heart_a_reply(
    reply_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        uid = UUID(user_id)
        await assert_not_banned(conn, uid)
        await communities_service.heart_reply(conn, UUID(reply_id), uid)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to heart reply. Please try again later.',
        )


@replies_router.delete('/{reply_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_a_reply(
    reply_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        await communities_service.delete_reply(conn, UUID(reply_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to delete reply. Please try again later.',
        )


@replies_router.delete('/{reply_id}/heart', status_code=status.HTTP_204_NO_CONTENT)
async def unheart_a_reply(
    reply_id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_consented_user),
):
    try:
        await communities_service.unheart_reply(conn, UUID(reply_id), UUID(user_id))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to unheart reply. Please try again later.',
        )
