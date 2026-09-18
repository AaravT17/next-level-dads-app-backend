from uuid import UUID

from fastapi import HTTPException, status

from app.common.config.constants import CONNECTION_NOTE_MAX_LENGTH
from app.modules.moderation.profanity_filter import check_profanity


def resolve_connection_status(user_id: UUID, requesting_id: UUID | None, connection_status: str | None) -> str | None:
    if connection_status == 'accepted':
        return 'connected'
    if connection_status == 'pending' and requesting_id == user_id:
        return 'pending_outgoing'
    if connection_status == 'pending' and requesting_id != user_id:
        return 'pending_incoming'
    if connection_status == 'blocked':
        return 'blocked'
    return None


def normalize_connection_note(note: str | None) -> str | None:
    """Trim a request note, treat blank as absent, and reject profanity (HTTP 400).

    Community content is moderated asynchronously because it is already public
    the moment it is posted; taking it down afterwards is the only option. A
    request note is different: it is delivered to exactly one person and is not
    visible to anyone until this insert succeeds, so it is cheaper and kinder to
    refuse it up front than to store it, show it, and delete it seconds later.
    The sender also gets to fix their wording instead of being silently filtered.

    Blocking here is only affordable because the classifier is a local word
    match — the ML layer is disabled (see moderation/toxicity.py), so there is
    no network hop on this path. If that layer is ever re-enabled, this should
    move back to a background task.
    """
    if note is None:
        return None

    cleaned = note.strip()
    if not cleaned:
        return None

    # Belt and braces: Pydantic already caps the length at the boundary, and the
    # connections table has a matching CHECK constraint.
    if len(cleaned) > CONNECTION_NOTE_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Your note must be {CONNECTION_NOTE_MAX_LENGTH} characters or fewer.',
        )

    if check_profanity(cleaned).flagged:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Please revise your note before sending this connection request.',
        )

    return cleaned
