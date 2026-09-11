from uuid import UUID


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
