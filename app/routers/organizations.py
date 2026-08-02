from fastapi import APIRouter, Depends, HTTPException, Query, status
import asyncpg
import json
from uuid import UUID

from app.dependencies.auth import get_current_user, get_admin_user
from app.dependencies.db import get_db
from app.models.organizations import (
    OrganizationApplicationCreate,
    OrganizationApplicationResponse,
    OrganizationApplicationDecision,
)
from app.services import organizations as organization_service

router = APIRouter(prefix='/api/organizations', tags=['organizations'])


def _parse_jsonb_fields(row: dict) -> dict:
    row['application_answers'] = json.loads(row['application_answers']) if row['application_answers'] else {}
    row['notes'] = json.loads(row['notes']) if row['notes'] else None
    return row


@router.post('/applications', response_model=OrganizationApplicationResponse, status_code=status.HTTP_201_CREATED)
async def submit_application(
    payload: OrganizationApplicationCreate,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        async with conn.transaction():
            query = """
                INSERT INTO organizations (
                    name, email, phone, city, province, website, description,
                    contact_name, contact_title, contact_email, contact_phone,
                    application_answers, status, admin_user_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'pending', $13)
                RETURNING *
            """
            res = await conn.fetchrow(
                query,
                payload.name,
                payload.email,
                payload.phone,
                payload.city,
                payload.province,
                payload.website,
                payload.description,
                payload.contact_name,
                payload.contact_title,
                payload.contact_email,
                payload.contact_phone,
                json.dumps(payload.application_answers),
                UUID(user_id),
            )
            await conn.execute(
                """
                INSERT INTO organization_representatives (organization_id, user_id)
                VALUES ($1, $2)
                """,
                res['id'],
                UUID(user_id),
            )
            return OrganizationApplicationResponse(**_parse_jsonb_fields(dict(res)))
    except Exception as e:
        print(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to submit application. Please try again later.',
        )


@router.get('/applications/me', response_model=OrganizationApplicationResponse)
async def get_my_application(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query = """
            SELECT o.*
            FROM organizations o
            JOIN organization_representatives r ON r.organization_id = o.id
            WHERE r.user_id = $1
            ORDER BY o.created_at DESC
            LIMIT 1
        """
        res = await conn.fetchrow(query, UUID(user_id))
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No application found.')
        return OrganizationApplicationResponse(**_parse_jsonb_fields(dict(res)))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch application. Please try again later.',
        )


@router.patch('/applications/me', response_model=OrganizationApplicationResponse)
async def update_my_application(
    payload: OrganizationApplicationCreate,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query = """
            UPDATE organizations o
            SET name = $2, email = $3, phone = $4, city = $5, province = $6, website = $7,
                description = $8, contact_name = $9, contact_title = $10,
                contact_email = $11, contact_phone = $12,
                application_answers = $13, updated_at = now()
            FROM organization_representatives r
            WHERE r.organization_id = o.id AND r.user_id = $1 AND o.status = 'pending'
            RETURNING o.*
        """
        res = await conn.fetchrow(
            query,
            UUID(user_id),
            payload.name,
            payload.email,
            payload.phone,
            payload.city,
            payload.province,
            payload.website,
            payload.description,
            payload.contact_name,
            payload.contact_title,
            payload.contact_email,
            payload.contact_phone,
            json.dumps(payload.application_answers),
        )
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='No pending application found.',
            )
        return OrganizationApplicationResponse(**_parse_jsonb_fields(dict(res)))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to update application. Please try again later.',
        )

# ── Admin Review  ─────────────────────────────────────────────

@router.get('/', response_model=list[OrganizationApplicationResponse])
async def list_organizations(
    status_filter: str | None = Query(None, alias='status'),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user)
):
    return await organization_service.list_organizations(conn=conn, status_filter=status_filter, limit=limit, offset=offset)


@router.get('/{organization_id}', response_model=OrganizationApplicationResponse)
async def get_organization(
    organization_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user)
):
    return await organization_service.get_organization(conn=conn, organization_id=organization_id)

@router.patch('/{organization_id}/decision', response_model=OrganizationApplicationResponse)
async def decide_application(
    organization_id: UUID,
    payload: OrganizationApplicationDecision,
    conn: asyncpg.Connection = Depends(get_db),
    _admin: str = Depends(get_admin_user)
):
    return await organization_service.decide_application(conn=conn, organization_id=organization_id, decision=payload)