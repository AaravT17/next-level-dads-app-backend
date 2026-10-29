import logging
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request, status
from supabase_auth.errors import AuthApiError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.common.config.constants import GHOST_ROLES, KNOWN_ROLES, ROLE_ADMIN
from app.common.config.supabase import get_supabase
import asyncpg
from app.common.dependencies.db import get_db

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller. `role` is None for a regular member."""

    id: str
    role: str | None


def read_role(user_id: str, app_metadata: dict | None) -> str | None:
    """Read the role from app_metadata.

    Return the role if it is a known role or None for no role.
    Raise a 403 for anything else.

    An unrecognized value is refused outright rather than downgraded to a regular
    member, so a mistyped role shows up as a locked-out account instead of
    silently granting the wrong access.
    """
    role = (app_metadata or {}).get('role', None)
    if role is None:
        return None
    # The isinstance check keeps an unhashable value (a list, say) from raising on the lookup.
    if isinstance(role, str) and role in KNOWN_ROLES:
        return role
    logger.warning('Refusing user %s: unrecognized role %r in app_metadata', user_id, role)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail='Your account role is not recognized.',
    )


def get_current_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    """Return the access token from the Authorization header."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing access token.')
    return credentials.credentials


async def resolve_current_user(token: str) -> CurrentUser | None:
    """Return the user an access token belongs to, or None if Supabase does not recognize it.

    Raises a 403 for an unrecognized role; any other failure propagates and the caller decides what it means.
    """
    supabase = get_supabase()
    try:
        res = await supabase.auth.get_user(token)
    except AuthApiError:
        return None
    if not res or not res.user:
        return None
    return CurrentUser(id=res.user.id, role=read_role(res.user.id, res.user.app_metadata))


async def get_current_user(request: Request, token: str = Depends(get_current_access_token)) -> CurrentUser:
    """Return the caller's id and role from the access token."""
    try:
        user = await resolve_current_user(token)
    except HTTPException:
        raise
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Something went wrong. Please try again later.',
        )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid or expired token.',
        )
    request.state.user_id = user.id
    request.state.role = user.role
    return user


async def get_customer(user: CurrentUser = Depends(get_current_user)) -> str:
    """Return the user_id if the user is a customer, and raise a 403 otherwise."""
    if user.role in GHOST_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='You cannot perform this action.',
        )
    return user.id


async def get_consented_customer(
    conn: asyncpg.Connection = Depends(get_db),
    user_id: str = Depends(get_customer),
) -> str:
    """Return the user_id only if the user is a customer who has accepted the T&C and Privacy Policy."""
    await _require_consent(conn, user_id)
    return user_id


async def get_viewer(
    conn: asyncpg.Connection = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> str:
    """Return the user_id for read-only routes: a ghost passes outright, anyone else must have consented."""
    if user.role not in GHOST_ROLES:
        await _require_consent(conn, user.id)
    return user.id


async def get_admin(user: CurrentUser = Depends(get_current_user)) -> str:
    """Return the user_id only if the user has the admin role."""
    if user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Admin access required.',
        )
    return user.id


async def _require_consent(conn: asyncpg.Connection, user_id: str):
    """Raise a 403 if the user has not accepted the T&C and Privacy Policy."""
    if not await check_consent(conn, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='You must accept the Terms and Conditions and Privacy Policy to continue.',
        )


async def check_consent(conn: asyncpg.Connection, user_id: str) -> bool:
    """Return True if the user has accepted both the T&C and Privacy Policy, and False otherwise."""
    return await conn.fetchval(
        """
        SELECT
            EXISTS (SELECT 1 FROM user_legal_acceptances WHERE user_id = $1 AND document_type = 'terms')
            AND
            EXISTS (SELECT 1 FROM user_legal_acceptances WHERE user_id = $1 AND document_type = 'privacy_policy')
        """,
        user_id,
    )
