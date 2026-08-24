import os
from fastapi import HTTPException, Response, status
from supabase_auth.errors import AuthApiError
from app.common.config.constants import IS_PRODUCTION, REFRESH_TOKEN_EXPIRY_DAYS
from app.common.config.supabase import get_supabase


async def register(email: str, password: str):
    supabase = get_supabase()
    try:
        await supabase.auth.sign_up(
            {
                'email': email,
                'password': password,
                'options': {'email_redirect_to': f'{os.getenv("FRONTEND_BASE_URL")}/verify-email'},
            }
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Something went wrong. Please try again later.',
        )


async def login(email: str, password: str, response: Response) -> str:
    supabase = get_supabase()
    try:
        res = await supabase.auth.sign_in_with_password(
            {
                'email': email,
                'password': password,
            }
        )
    except AuthApiError as e:
        if e.status == 400 and 'invalid login credentials' in e.message.lower():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid credentials.')
        if e.status == 400 and 'email not confirmed' in e.message.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Please verify your email before logging in.',
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Something went wrong. Please try again later.',
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Something went wrong. Please try again later.',
        )
    _set_refresh_cookie(response, res.session.refresh_token)
    return res.session.access_token


async def set_oauth_session(access_token: str, refresh_token: str, response: Response) -> str:
    supabase = get_supabase()
    try:
        user = await supabase.auth.get_user(access_token)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token.')
    except HTTPException:
        raise
    except AuthApiError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token.')
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Something went wrong. Please try again later.',
        )
    _set_refresh_cookie(response, refresh_token)
    return access_token


async def logout(access_token: str, response: Response):
    supabase = get_supabase()
    try:
        await supabase.auth.admin.sign_out(access_token, 'local')
    except Exception:
        pass  # clear the cookie even if sign out fails
    _clear_refresh_cookie(response)


async def refresh(refresh_token: str, response: Response) -> str:
    supabase = get_supabase()
    try:
        res = await supabase.auth.refresh_session(refresh_token)
    except AuthApiError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid or expired refresh token.',
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Something went wrong. Please try again later.',
        )
    _set_refresh_cookie(response, res.session.refresh_token)
    return res.session.access_token


async def verify_token(token: str) -> str | None:
    supabase = get_supabase()
    try:
        res = await supabase.auth.get_user(token)
        return res.user.id if res.user else None
    except Exception:
        return None


def _set_refresh_cookie(response: Response, refresh_token: str):
    response.set_cookie(
        key='refresh_token',
        value=refresh_token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite='lax',
        domain='.nextleveldads.ca' if IS_PRODUCTION else None,
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRY_DAYS,
    )


def _clear_refresh_cookie(response: Response):
    response.delete_cookie(
        key='refresh_token',
        httponly=True,
        secure=IS_PRODUCTION,
        samesite='lax',
        domain='.nextleveldads.ca' if IS_PRODUCTION else None,
    )
