from uuid import UUID


def resolve_connection_status(
    user_id: UUID, requesting_id: UUID | None, status: str | None
) -> str | None:
    if status == "accepted":
        return "connected"
    if status == "pending" and requesting_id == user_id:
        return "pending_outgoing"
    if status == "pending" and requesting_id != user_id:
        return "pending_incoming"
    if status == "blocked":
        return "blocked"
    return None
