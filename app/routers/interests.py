from fastapi import APIRouter, HTTPException, status, Depends
from app.dependencies.auth import get_current_user
from app.config.supabase import get_supabase

router = APIRouter(prefix="/api/interests", tags=["interests"])


@router.get("/")
async def get_interests(user_id: str = Depends(get_current_user)):
    supabase = get_supabase()
    try:
        res = await supabase.from_("interests").select("name").order("name").execute()
        return [interest["name"] for interest in res.data]
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch interests. Please try again later.",
        )
