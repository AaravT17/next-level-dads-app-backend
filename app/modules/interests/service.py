from fastapi import HTTPException, status
from app.common.config.supabase import get_supabase


async def get_interests() -> list[str]:
    supabase = get_supabase()
    try:
        res = await supabase.from_('interests').select('name').order('name').execute()
        return [interest['name'] for interest in res.data]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to fetch interests. Please try again later.',
        )
