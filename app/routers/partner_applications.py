from fastapi import APIRouter, Depends, HTTPException, Query, status
import asyncpg
from uuid import UUID

from app.dependencies.auth import get_current_user, get_admin_user
from app.dependencies.db import get_db
from app.models.partner_applications import (
    PartnerApplicationCreate,
    PartnerApplicationResponse,
    PartnerApplicationDecision,
)

router = APIRouter(prefix='/api/partner-applications', tags=['partner-applications'])


@router.post('/', response_model=PartnerApplicationResponse, status_code=status.HTTP_201_CREATED)
async def submit_application(
    payload: PartnerApplicationCreate,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query = """
            INSERT INTO organizations (
                name, type, email, phone, city, province, website, description, app_status, main_org_rep
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', $9)
            RETURNING *
        """
        res = await conn.fetchrow(
            query,
            payload.name,
            payload.type,
            payload.email,
            payload.phone,
            payload.city,
            payload.province,
            payload.website,
            payload.description,
            UUID(user_id),
        )
        return PartnerApplicationResponse(**dict(res))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to submit application. Please try again later.',
        )


@router.get('/me', response_model=PartnerApplicationResponse)
async def get_my_application(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query = """
            SELECT *
            FROM organizations
            WHERE main_org_rep = $1
            ORDER BY created_at DESC
            LIMIT 1
        """
        res = await conn.fetchrow(query, UUID(user_id))
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No application found.')
        return PartnerApplicationResponse(**dict(res))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch application. Please try again later.',
        )


@router.patch('/me', response_model=PartnerApplicationResponse)
async def update_my_application(
    payload: PartnerApplicationCreate,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query = """
            UPDATE organizations
            SET name = $2, type = $3, email = $4, phone = $5, city = $6, province = $7,
                website = $8, description = $9, updated_at = now()
            WHERE main_org_rep = $1 AND app_status = 'pending'
            RETURNING *
        """
        res = await conn.fetchrow(
            query,
            UUID(user_id),
            payload.name,
            payload.type,
            payload.email,
            payload.phone,
            payload.city,
            payload.province,
            payload.website,
            payload.description,
        )
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='No pending application found.',
            )
        return PartnerApplicationResponse(**dict(res))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to update application. Please try again later.',
        )


@router.get('/', response_model=list[PartnerApplicationResponse])
async def list_applications(
    status_filter: str | None = Query(None, alias='status'),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        query = """
            SELECT *
            FROM organizations
            WHERE ($1::text IS NULL OR app_status = $1)
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
        """
        res = await conn.fetch(query, status_filter, limit, offset)
        return [PartnerApplicationResponse(**dict(r)) for r in res]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch applications. Please try again later.',
        )


@router.get('/{id}', response_model=PartnerApplicationResponse)
async def get_application(
    id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        query = """
            SELECT *
            FROM organizations
            WHERE id = $1
        """
        res = await conn.fetchrow(query, id)
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Application not found.')
        return PartnerApplicationResponse(**dict(res))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch application. Please try again later.',
        )


@router.patch('/{id}/decision', response_model=PartnerApplicationResponse)
async def decide_application(
    id: UUID,
    payload: PartnerApplicationDecision,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user),
):
    try:
        query = """
            UPDATE organizations
            SET app_status = $2,
                accepted_at = CASE WHEN $2 = 'approved' THEN now() ELSE accepted_at END,
                updated_at = now()
            WHERE id = $1 AND app_status = 'pending'
            RETURNING *
        """
        res = await conn.fetchrow(query, id, payload.app_status)
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No pending application found.')
        return PartnerApplicationResponse(**dict(res))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to record decision. Please try again later.',
        )
