from fastapi import APIRouter, Depends, HTTPException, status
import asyncpg
import json
from uuid import UUID

from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
from app.models.organization_chats import OrganizationChatResponse, OrganizationMessageResponse

router = APIRouter(prefix='/organization-chats', tags=['organization-chats'])


def _parse_subject(row: dict) -> dict:
    row['subject'] = json.loads(row['subject']) if row['subject'] else None
    return row


@router.get('/me', response_model=OrganizationChatResponse)
async def get_my_chat(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query = """
            SELECT c.*
            FROM organization_chats c
            JOIN organization_representatives r ON r.organization_id = c.organization_id
            WHERE r.user_id = $1
        """
        res = await conn.fetchrow(query, UUID(user_id))
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No chat found.')
        return OrganizationChatResponse(**dict(res))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch chat. Please try again later.',
        )


@router.get('/{chat_id}/messages', response_model=list[OrganizationMessageResponse])
async def get_chat_messages(
    chat_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        access_query = """
            SELECT
                EXISTS (
                    SELECT 1
                    FROM organization_chats c
                    JOIN organization_representatives r ON r.organization_id = c.organization_id
                    WHERE c.id = $1 AND r.user_id = $2
                ) AS is_own_chat,
                COALESCE((SELECT is_admin FROM public.users WHERE id = $2), false) AS is_admin
        """
        access = await conn.fetchrow(access_query, chat_id, UUID(user_id))
        if not access or not (access['is_own_chat'] or access['is_admin']):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Access denied.')

        query = """
            SELECT *
            FROM organization_messages
            WHERE chat_id = $1
            ORDER BY created_at ASC
        """
        rows = await conn.fetch(query, chat_id)
        return [OrganizationMessageResponse(**_parse_subject(dict(r))) for r in rows]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch messages. Please try again later.',
        )
