from uuid import UUID


def build_get_organization_event_by_id_query(
    event_id: UUID,
) -> tuple[str, list]:
    """
    Fetch one organization-hosted event application.
    """
    query = """
        SELECT
            e.*,
            o.name AS organization_name
        FROM events e
        LEFT JOIN organizations o ON o.id = e.hosted_by_org_id
        WHERE e.id = $1
          AND e.hosted_by_org_id IS NOT NULL
    """
    params = [event_id]
    return query, params


def build_list_organization_events_query(
    search: str | None = None,
    region: str | None = None,
    organization: str | None = None,
    format: str | None = None,
    category: str | None = None,
    status: str | None = None,
) -> tuple[str, list]:
    """
    List organization-hosted events for admin Events page.
    """
    query = """
        SELECT
            e.id,
            e.name,
            COALESCE(o.name, 'Unknown Organization') AS organization_name,
            e.starts_at AS event_date,
            COALESCE(att.rsvp_count, 0)::int AS rsvps,
            0::int AS attended,
            0.0 AS attendance_rate,
            e.app_status AS status,
            e.location AS region,
            e.type AS format,
            NULL::text AS category
        FROM events e
        LEFT JOIN organizations o
            ON o.id = e.hosted_by_org_id
        LEFT JOIN (
            SELECT event_id, COUNT(*)::int AS rsvp_count
            FROM event_attendees
            GROUP BY event_id
        ) att ON att.event_id = e.id
        WHERE e.hosted_by_org_id IS NOT NULL
    """

    params: list = []
    param_index = 1

    if search:
        query += f"""
          AND (
            e.name ILIKE ${param_index}
            OR o.name ILIKE ${param_index}
          )
        """
        params.append(f"%{search}%")
        param_index += 1

    if region and region.lower() not in {"all regions", "all"}:
        query += f" AND e.location ILIKE ${param_index}"
        params.append(f"%{region}%")
        param_index += 1

    if organization and organization.lower() not in {"all organizations", "all"}:
        query += f" AND o.name ILIKE ${param_index}"
        params.append(f"%{organization}%")
        param_index += 1

    if format and format.lower() not in {"all formats", "all"}:
        normalized = format.lower().replace(" ", "_")
        if normalized in {"in_person", "in-person"}:
            normalized = "local"
        elif normalized == "online":
            normalized = "virtual"
        query += f" AND e.type ILIKE ${param_index}"
        params.append(normalized)
        param_index += 1

    if status and status.lower() not in {"all status", "all"}:
        normalized_status = status.lower().replace(" ", "_")
        query += f" AND e.app_status ILIKE ${param_index}"
        params.append(normalized_status)
        param_index += 1

    _ = category

    query += """
        ORDER BY e.starts_at DESC NULLS LAST, e.created_at DESC
    """
    return query, params


def build_update_organization_event_decision_query(
    event_id: UUID,
    status: str,
    admin_notes: str | None = None,
    admin_user_id: str | None = None,
) -> tuple[str, list]:
    """
    Update app_status and optionally admin_notes (jsonb).
    """
    query = """
        UPDATE events
        SET
            app_status = $2,
            admin_notes = CASE
                WHEN $3::text IS NULL THEN admin_notes
                ELSE jsonb_build_object(
                    'text', $3::text,
                    'created_by', COALESCE(
                        admin_notes->>'created_by',
                        $4::text
                    ),
                    'created_at', COALESCE(
                        (admin_notes->>'created_at')::timestamptz,
                        NOW()
                    ),
                    'updated_at', NOW()
                )
            END
        WHERE id = $1
          AND hosted_by_org_id IS NOT NULL
        RETURNING id, app_status, admin_notes
    """
    params = [event_id, status, admin_notes, admin_user_id]
    return query, params
