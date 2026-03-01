from fastapi import Depends, HTTPException, status
from supabase_auth.errors import AuthApiError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config.supabase import get_supabase

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token."
        )
    return credentials.credentials


async def get_current_user(token: str = Depends(get_current_access_token)):
    supabase = get_supabase()
    try:
        res = await supabase.auth.get_user(token)
        if not res.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
            )
        return res.user.id
    except AuthApiError as _:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later.",
        )
