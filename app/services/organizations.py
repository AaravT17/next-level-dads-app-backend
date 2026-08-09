import json

import asyncpg
from app.models.organizations import OrganizationApplicationDecision, OrganizationAdminApplicationResponse, InternalNoteResponse, OrganizationSummaryResponse
from uuid import UUID
from fastapi import HTTPException, status
from app.utils.json_utils import parse_jsonb_fields, parse_jsonb_value

async def list_organizations(
    conn: asyncpg.Connection,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> list[OrganizationSummaryResponse]:
        query = """
                SELECT 
                    id, 
                    name, 
                    status, 
                    created_at, 
                    updated_at
                FROM organizations
                WHERE ($1::text IS NULL OR status = $1)
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """

        rows = await conn.fetch(query, status_filter, limit, offset)

        return [OrganizationSummaryResponse(**dict(row))
                    for row in rows
        ]


async def get_organization(
    conn: asyncpg.Connection,
    organization_id: UUID,
) -> OrganizationAdminApplicationResponse:
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

    organization = parse_jsonb_fields(dict(row))
    notes = organization.get("notes", [])

    # Resolve internal note author IDs to display names for the admin note history.
    submitted_by_ids = {
        UUID(note["submitted_by"])
        for note in notes
        if note.get("submitted_by")
    }

    submitted_by_names: dict[str, str] = {}

    if submitted_by_ids:
        users = await conn.fetch(
            """
            SELECT id, name
            FROM public.users
            WHERE id = ANY($1::uuid[])
            """,
            list(submitted_by_ids),
        )

        submitted_by_names = {
            str(user["id"]): user["name"]
            for user in users
        }

        for note in notes:
            submitted_by = note.get("submitted_by")

            note["submitted_by_name"] = (
                submitted_by_names.get(str(submitted_by))

                if submitted_by
                else None
            )

    organization["notes"] = notes

    return OrganizationAdminApplicationResponse(**organization)

async def add_internal_note(
    conn: asyncpg.Connection,
    organization_id: UUID,
    submitted_by: UUID,
    content: str,
) -> InternalNoteResponse:
    query = """
        UPDATE organizations
        SET
            notes = notes || jsonb_build_array(
                jsonb_build_object(
                    'id', gen_random_uuid(),
                    'submitted_by', $2::text,
                    'content', $3::text,
                    'submitted_at', now()
                )
            ),
            updated_at = now()
        WHERE id = $1
          AND status = 'pending'
        RETURNING notes -> -1 AS saved_note
    """

    row = await conn.fetchrow(
        query,
        organization_id,
        str(submitted_by),
        content,
    )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending organization application not found.",
        )

    saved_note = parse_jsonb_value(row["saved_note"], {})

    return InternalNoteResponse(**saved_note)


async def decide_application(
    conn: asyncpg.Connection,
    organization_id: UUID,
    decision: OrganizationApplicationDecision,
) -> OrganizationAdminApplicationResponse:
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
    return OrganizationAdminApplicationResponse(**parse_jsonb_fields(dict(row)))
