import asyncpg
from fastapi import HTTPException, status
from app.modules.interests.models import InterestResponse


async def get_interests(conn: asyncpg.Connection) -> list[InterestResponse]:
    try:
        rows = await conn.fetch('SELECT id, slug, name FROM interests ORDER BY name')
        return [InterestResponse(**dict(r)) for r in rows]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch interests. Please try again later.',
        )
