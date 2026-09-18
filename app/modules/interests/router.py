from fastapi import APIRouter, Depends
from app.common.dependencies.auth import get_current_user
from app.common.dependencies.db import get_db
from app.modules.interests.models import InterestResponse
import app.modules.interests.service as interests_service
import asyncpg


router = APIRouter(prefix='/api/interests', tags=['interests'])


@router.get('/', response_model=list[InterestResponse])
async def get_interests(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    return await interests_service.get_interests(conn)
