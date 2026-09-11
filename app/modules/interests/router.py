from fastapi import APIRouter, Depends
from app.common.dependencies.auth import get_current_user
import app.modules.interests.service as interests_service


router = APIRouter(prefix='/api/interests', tags=['interests'])


@router.get('/')
async def get_interests(user_id: str = Depends(get_current_user)):
    return await interests_service.get_interests()
