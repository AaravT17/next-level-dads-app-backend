from fastapi import Depends, HTTPException, Request, status
from supabase_auth.errors import AuthApiError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config.supabase import get_supabase
import asyncpg
from app.dependencies.db import get_db
from app.utils.auth import check_consent

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing access token.')
    return credentials.credentials


async def get_current_user(request: Request, token: str = Depends(get_current_access_token)):
    supabase = get_supabase()
    try:
        res = await supabase.auth.get_user(token)
        if not res.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Invalid or expired token.',
            )
        request.state.user_id = res.user.id
        # Store app metadata for downstream account-type authorization in get_dad_app_access_user().
        request.state.app_metadata = res.user.app_metadata or {}

        return res.user.id
    except AuthApiError as _:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid or expired token.',
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Something went wrong. Please try again later.',
        )

async def get_dad_app_access_user(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> str: 
    """Return the user_id unless the authenticated user is an organization account.
    
    Partner Portal organization accounts are identified by `user_type="organizations"` in
    Supabase app metadata. Users without this value continue through the
    existing Dad app authorization flow.
    """

    app_metadata = getattr(request.state, "app_metadata", {})
    user_type = app_metadata.get("user_type")

    # Organization accounts cannot access Dad app features.
    if user_type == "organizations":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Partner Portal accounts can't be used in the Dad app. Create a Dad account with a different email address to continue.",
        )
    return user_id

async def get_consented_user(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_dad_app_access_user),
) -> str:
    """Return the user_id only if the user is not an organization account and the user has accepted the T&C and Privacy Policy."""
    accepted = await check_consent(conn, user_id)
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='You must accept the Terms and Conditions and Privacy Policy to continue.',
        )
    return user_id


async def get_admin_user(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_current_user),
) -> str:
    """Return the user_id only if the user has is_admin = TRUE."""
    is_admin = await conn.fetchval(
        'SELECT is_admin FROM public.users WHERE id = $1',
        user_id,
    )
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Admin access required.',
        )
    return user_id