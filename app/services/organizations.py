import asyncpg
from app.models.organizations import OrganizationApplicationResponse, OrganizationApplicationDecision
from uuid import UUID
from fastapi import HTTPException, status
from app.utils.organizations import parse_jsonb_fields

async def list_organizations(
    conn: asyncpg.Connection,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> list[OrganizationApplicationResponse]:
        query = """
                SELECT *
                FROM organizations
                WHERE ($1::text IS NULL OR status = $1)
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """

        rows = await conn.fetch(query, status_filter, limit, offset)

        return [OrganizationApplicationResponse(
                    **parse_jsonb_fields(dict(row)))
                    for row in rows
        ]

async def get_organization(
    conn: asyncpg.Connection,
    organization_id: UUID,
) -> OrganizationApplicationResponse:
    query = """
        SELECT *
        FROM organizations
        WHERE id = $1
    """
    row = await conn.fetchrow(query, organization_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Organization not found.',
        )
    return OrganizationApplicationResponse(**parse_jsonb_fields(dict(row)))

async def decide_application(
    conn: asyncpg.Connection,
    organization_id: UUID,
    decision: OrganizationApplicationDecision,
) -> OrganizationApplicationResponse:
    query = """
        UPDATE organizations
        SET status = $2,
            approved_at = CASE 
                WHEN $2 = 'approved' THEN now()
                ELSE approved_at
            END,
            updated_at = now()
        WHERE id = $1
            AND status = 'pending'
        RETURNING *
    """
    row = await conn.fetchrow(query, organization_id, decision.status)

    if not row:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='Organization was not found or is no longer pending.',
        )
    return OrganizationApplicationResponse(**parse_jsonb_fields(dict(row)))
