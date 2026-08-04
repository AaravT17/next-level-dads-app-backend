from uuid import UUID


def build_get_organization_event_by_id_query(
        event_id: UUID,
) -> tuple[str,list]:

    """
    Build the SQL to fetch one organization event application.
    TODO: Replace with real query once confirmed all needed columns.
    """

    query = """
        SELECT e.*
        From events e
        Where e.iid = $1
            and e.hosted_by_org_id IS NOT NULL
        """
    params = [event_id]
    return query, params

def build_update_organization_event_decision_query(
        event_id: UUID,
        status: str,
        admin_notes: str | None = None,
        admin_user_id: str | None = None,
) -> tuple[str, list]:
    """
    Update app_status and optionally admin_notes (jsonb) on an organization event.
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
                        admin_notes->> 'created_by',
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
