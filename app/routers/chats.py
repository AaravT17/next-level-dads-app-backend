from fastapi import APIRouter, Depends, status, HTTPException
from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
import asyncpg
from app.models.chats import CreateChatRequest

router = APIRouter(
    prefix='/api/chats',
    tags=['chats'],
)


@router.get('/')
async def get_chats(
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    return []


@router.post('/', status_code=status.HTTP_201_CREATED)
async def create_chat(
    body: CreateChatRequest,
    user_id: str = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db),
):
    name, participant_ids = body.name, body.participant_ids
    # validate the participant IDs: they must exist, be connected with the current user, and not include the current
    # user (checking that they are connected with the current user also implicitly checks that they exist, since you
    # can't be connected with a non-existent user, and that they do not include the current user, since you can't be
    # connected with yourself)
    try:
        connections = await conn.fetch(
            """
            SELECT
                (CASE WHEN requesting_id = $1 THEN requested_id ELSE requesting_id END) AS user_id
            FROM connections
            WHERE (requesting_id = $1 OR requested_id = $1) AND status = 'accepted'
            """,
            *[user_id],
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to create chat. Please try again later.',
        )

    s = set(r['user_id'] for r in connections)
    if any(pid not in s for pid in participant_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid participant IDs')

    # input validation complete, create the chat and the corresponding chat_participants entries

    if len(participant_ids) == 1:
        # create a DM chat
        try:
            async with conn.transaction():
                chat_id = await conn.fetchval(
                    """
                    INSERT INTO chats (type, dm_user_1, dm_user_2)
                    VALUES ('dm', $1, $2)
                    RETURNING id
                    """,
                    *[user_id, participant_ids[0]],
                )
                await conn.executemany(
                    """
                    INSERT INTO chat_participants (chat_id, user_id)
                    VALUES ($1, $2)
                    """,
                    [(chat_id, user_id), (chat_id, participant_ids[0])],
                )
                # being admin does not make sense or matter for DM chats
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='A DM chat with this user already exists')
        except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to create chat. Please try again later.',
            )
    else:
        # create a group chat
        try:
            async with conn.transaction():
                chat_id = await conn.fetchval(
                    """
                    INSERT INTO chats (type, name)
                    VALUES ('group', $1)
                    RETURNING id
                    """,
                    *[name],
                )
                await conn.executemany(
                    """
                    INSERT INTO chat_participants (chat_id, user_id, is_admin)
                    VALUES ($1, $2, $3)
                    """,
                    [(chat_id, pid, False) for pid in participant_ids] + [(chat_id, user_id, True)],
                )
        except Exception as _:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to create chat. Please try again later.',
            )
    return {'id': str(chat_id)}


@router.get('/{chat_id}')
async def get_chat(chat_id: str):
    return {}


@router.get('/{chat_id}/messages')
async def get_chat_messages(chat_id: str):
    return []


@router.post('/{chat_id}/messages')
async def send_message(chat_id: str):
    return {}


@router.patch('/{chat_id}/messages/{message_id}')
async def edit_message(chat_id: str, message_id: str):
    return {}


@router.delete('/{chat_id}/messages/{message_id}')
async def delete_message(chat_id: str, message_id: str):
    return {}
