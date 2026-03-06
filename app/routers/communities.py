from fastapi import APIRouter, Depends, HTTPException, status
from app.dependencies.auth import get_current_user
from app.models.communities import CommunityResponse
from app.dependencies.db import get_db
import asyncpg
from app.services.communities import build_discover_communities_query
from uuid import UUID
from datetime import datetime

router = APIRouter(
    prefix="/api/communities",
    tags=["communities"],
)


@router.get("/", response_model=list[CommunityResponse])
async def get_communities(
    name: str | None = None,
    cursor_id: str | None = None,
    cursor_created_at: str | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_discover_communities_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=datetime(cursor_created_at)
            if cursor_created_at
            else None,
        )
        res = await conn.fetch(query, *params)
        return [CommunityResponse(**dict(r)) for r in res]
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        print(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch communities. Please try again later.",
        )
