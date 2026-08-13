import json

import asyncpg
from app.models.organizations import (
    InternalNotePreviewResponse, 
    OrganizationApplicationDecision, 
    OrganizationAdminApplicationResponse, 
    InternalNoteResponse, 
    ActionItemResponse,
    ApplicationRowResponse, 
    ActivePartnerResponse)
from uuid import UUID
from fastapi import HTTPException, status
from app.utils.json_utils import parse_jsonb_fields, parse_jsonb_value

async def list_organizations(
    conn: asyncpg.Connection,
    status_filter: str | None,
    limit: int,
    offset: int,
    search: str | None = None,
) -> list[ApplicationRowResponse]:
        query = """
            SELECT
                o.id,
                o.name,
                o.status,
                o.city,
                o.province,
                o.contact_name,
                o.created_at,
                o.updated_at,
                last_note.content AS last_note_content,
                last_note.submitted_at AS last_note_submitted_at,
                u.name AS last_note_submitted_by_name
            FROM organizations o
            
            LEFT JOIN LATERAL (
                SELECT
                    note ->> 'content' AS content,
                    (note ->> 'submitted_by')::uuid AS submitted_by,
                    (note ->> 'submitted_at')::timestamptz AS submitted_at
                FROM jsonb_array_elements(o.notes)
                    WITH ORDINALITY AS n(note, position)
                ORDER BY position DESC
                LIMIT 1
            ) last_note ON TRUE

            LEFT JOIN public.users u
                ON u.id = last_note.submitted_by
            WHERE o.status IN ('pending', 'rejected')
                AND ($1::text IS NULL OR o.status = $1)
                AND (
                    $2::text IS NULL
                    OR o.name ILIKE '%' || $2 || '%'
                    OR o.contact_name ILIKE '%' || $2 || '%'
                )
            ORDER BY
                CASE
                    WHEN o.status = 'pending' THEN 0
                    ELSE 1
                END,
                o.created_at DESC
            LIMIT $3 OFFSET $4
        """

        rows = await conn.fetch(query, status_filter, search, limit, offset)

        applications: list[ApplicationRowResponse] = []

        for row in rows:
            last_internal_note = None

            if row["last_note_content"] is not None:
                last_internal_note = InternalNotePreviewResponse(
                    submitted_by_name=row["last_note_submitted_by_name"],
                    content=row["last_note_content"],
                    submitted_at=row["last_note_submitted_at"],
                )

            applications.append(
                ApplicationRowResponse(
                    id=row["id"],
                    name=row["name"],
                    status=row["status"],
                    city=row["city"],
                    province=row["province"],
                    contact_name=row["contact_name"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    last_internal_note=last_internal_note,
                )
            )

        return applications


async def list_active_partners(
    conn: asyncpg.Connection,
    limit: int,
    offset: int,
    search: str | None = None,
) -> list[ActivePartnerResponse]:
        query = """
                SELECT 
                    o.id, 
                    o.name, 
                    o.city,
                    o.province,
                    o.contact_name,
                    o.approved_at
                FROM organizations o
                WHERE o.status = 'approved'
                    AND (
                        $1::text IS NULL
                        OR o.name ILIKE '%' || $1 || '%'
                        OR o.contact_name ILIKE '%' || $1 || '%'
                    )
                ORDER BY o.approved_at DESC
                LIMIT $2 OFFSET $3
            """

        rows = await conn.fetch(query, search, limit, offset)

        return [
             ActivePartnerResponse(
                id=row["id"],
                name=row["name"],
                city=row["city"],
                province=row["province"],
                contact_name=row["contact_name"],
                approved_at=row["approved_at"]
            )
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
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization was not found or is no longer pending.",
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
