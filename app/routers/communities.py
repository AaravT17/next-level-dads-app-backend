from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from app.dependencies.auth import get_current_user
from app.models.communities import CommunityResponse
from app.models.users import CommunityMemberResponse
from app.dependencies.db import get_db
import asyncpg
from app.services.communities import (
    build_discover_communities_query,
    build_get_community_by_id_query,
    build_get_community_members_query,
)
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
    cursor_created_at: datetime | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_discover_communities_query(
            user_id=UUID(user_id),
            name=name,
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_created_at=cursor_created_at,
        )
        res = await conn.fetch(query, *params)
        return [CommunityResponse(**dict(r)) for r in res]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch communities. Please try again later.",
        )


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_community(
    name: str = Body(..., max_length=100),
    description: str | None = Body(None, max_length=500),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        async with conn.transaction():
            query = """
                INSERT INTO communities (name, description, created_by, created_at)
                VALUES ($1, $2, $3, NOW())
                RETURNING id
            """
            res = await conn.fetchrow(query, *[name, description, UUID(user_id)])
            if not res:
                raise Exception("Failed to create community.")
            community_id = res["id"]
            query = """
                INSERT INTO community_members (community_id, user_id, role, joined_at)
                VALUES ($1, $2, 'admin', NOW())
            """
            await conn.execute(query, *[community_id, UUID(user_id)])
        return {"id": str(community_id)}
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create community. Please try again later.",
        )


@router.get("/{id}", response_model=CommunityResponse)
async def get_community_by_id(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_get_community_by_id_query(
            id=UUID(id), user_id=UUID(user_id)
        )
        res = await conn.fetchrow(query, *params)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Community not found.",
            )
        return CommunityResponse(**dict(res))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch community details. Please try again later.",
        )


@router.get("/{id}/members", response_model=list[CommunityMemberResponse])
async def get_community_members(
    id: str,
    cursor_id: str | None = Query(None),
    cursor_joined_at: datetime | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        query, params = build_get_community_members_query(
            id=UUID(id),
            cursor_id=UUID(cursor_id) if cursor_id else None,
            cursor_joined_at=cursor_joined_at,
        )
        res = await conn.fetch(query, *params)
        return [CommunityMemberResponse(**dict(r)) for r in res]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch community members. Please try again later.",
        )


@router.post("/{id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def join_community(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        id, user_id = UUID(id), UUID(user_id)
        query = """
            INSERT INTO community_members (community_id, user_id, role, joined_at)
            VALUES ($1, $2, 'member', NOW())
            ON CONFLICT (community_id, user_id) DO NOTHING
        """
        await conn.execute(query, *[id, user_id])
        return
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to join community. Please try again later.",
        )


@router.delete("/{id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def leave_community(
    id: str,
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        id, user_id = UUID(id), UUID(user_id)
        query = """
            DELETE FROM community_members
            WHERE community_id = $1 AND user_id = $2
        """
        await conn.execute(query, *[id, user_id])
        return
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to leave community. Please try again later.",
        )
