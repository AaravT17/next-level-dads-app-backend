from fastapi import APIRouter, Depends, HTTPException, Query, status
import asyncpg
from uuid import UUID

from app.dependencies.auth import get_current_user, get_admin_user
from app.dependencies.db import get_db
from app.models.partner_applications import PartnerApplicationCreate, PartnerApplicationResponse, PartnerApplicationDecision

router = APIRouter(prefix='/api/partner-applications', tags=['partner-applications'])


@router.post('/', response_model=PartnerApplicationResponse, status_code=status.HTTP_201_CREATED)
async def submit_application(
    payload: PartnerApplicationCreate,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query = """
            INSERT INTO partner_applications (
                submitted_by, organization_name, organization_type, region, website, mission,
                representative_name, representative_title, representative_email, representative_phone,
                primary_goals, partnership_reason, estimated_reach, status
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'pending')
            RETURNING *
        """
        res = await conn.fetchrow(
            query,
            UUID(user_id),
            payload.organization_name,
            payload.organization_type,
            payload.region,
            payload.website,
            payload.mission,
            payload.representative_name,
            payload.representative_title,
            payload.representative_email,
            payload.representative_phone,
            payload.primary_goals,
            payload.partnership_reason,
            payload.estimated_reach,
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
            FROM partner_applications
            WHERE submitted_by = $1
            ORDER BY submitted_at DESC
            LIMIT 1
        """
        res = await conn.fetchrow(query, UUID(user_id))
        if not res:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No applications found')
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
            UPDATE partner_applications
            SET organization_name = $2, organization_type = $3, region = $4, website = $5, mission = $6,
                representative_name = $7, representative_title = $8, representative_email = $9,
                representative_phone = $10, primary_goals = $11, partnership_reason = $12,
                estimated_reach = $13, status = 'pending'
            WHERE submitted_by = $1 AND status = 'needs_changes' 
            RETURNING *
        """
        res = await conn.fetchrow(
            query,
            UUID(user_id),
            payload.organization_name,
            payload.organization_type,
            payload.region,
            payload.website,
            payload.mission,
            payload.representative_name,
            payload.representative_title,
            payload.representative_email,
            payload.representative_phone,
            payload.primary_goals,
            payload.partnership_reason,
            payload.estimated_reach,
        )
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='No application awaiting changes was found.',
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
            FROM partner_applications
            WHERE ($1::text IS NULL OR status = $1)
            ORDER BY submitted_at DESC
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
            FROM partner_applications
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
    admin_id: str = Depends(get_admin_user),
):
    try:
        async with conn.transaction():
            query = """
                UPDATE partner_applications
                SET status = $2, decision_message = $3, admin_notes = $4, reviewed_by = $5
                WHERE id = $1 AND status = 'pending'
                RETURNING *
            """
            res = await conn.fetchrow(
                query, id, payload.status, payload.decision_message, payload.admin_notes, UUID(admin_id)
            )
            if not res:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No pending application found.')
            application = dict(res)

            if payload.status == 'approved':
                org_query = """
                    INSERT INTO organizations (name, type, region, website, mission, status)
                    VALUES ($1, $2, $3, $4, $5, 'active')
                    RETURNING id
                """
                org_res = await conn.fetchrow(
                    org_query,
                    application['organization_name'],
                    application['organization_type'],
                    application['region'],
                    application['website'],
                    application['mission'],
                )
                organization_id = org_res['id']

                rep_query = """
                    INSERT INTO organization_representatives (auth_user_id, name, title, email, phone)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (auth_user_id) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                """
                rep_res = await conn.fetchrow(
                    rep_query,
                    application['submitted_by'],
                    application['representative_name'],
                    application['representative_title'],
                    application['representative_email'],
                    application['representative_phone'],
                )
                representative_id = rep_res['id']

                await conn.execute(
                    """
                    INSERT INTO organization_memberships (organization_id, representative_id)
                    VALUES ($1, $2)
                    """,
                    organization_id,
                    representative_id,
                )

                res = await conn.fetchrow(
                    """
                    UPDATE partner_applications SET organization_id = $2 WHERE id = $1 RETURNING *
                    """,
                    id,
                    organization_id,
                )

            return PartnerApplicationResponse(**dict(res))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to record decision. Please try again later.',
        )
