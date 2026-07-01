import re
from app.config.constants import MIN_PASSWORD_LENGTH, PASSWORD_SPECIAL_CHARACTERS
import os
from fastapi import Response
from app.config.constants import REFRESH_TOKEN_EXPIRY_DAYS
from app.config.supabase import get_supabase


def validate_password_strength(pwd: str) -> str:
    if len(pwd) < MIN_PASSWORD_LENGTH:
        raise ValueError(f'Password must be at least {MIN_PASSWORD_LENGTH} characters long')
    if not any(char.isdigit() for char in pwd):
        raise ValueError('Password must contain at least one digit')
    if not any(char.isalpha() and char.isupper() for char in pwd):
        raise ValueError('Password must contain at least one uppercase letter')
    if not any(char.isalpha() and char.islower() for char in pwd):
        raise ValueError('Password must contain at least one lowercase letter')
    if not re.search(PASSWORD_SPECIAL_CHARACTERS, pwd):
        raise ValueError('Password must contain at least one special character')
    return pwd


def strip_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError('Email must be a string')
    email = email.strip()
    if len(email) == 0:
        raise ValueError('Email cannot be empty')
    return email


def set_refresh_cookie(response: Response, refresh_token: str):
    response.set_cookie(
        key='refresh_token',
        value=refresh_token,
        httponly=True,
        secure=os.getenv('ENV') == 'production',
        samesite='None' if os.getenv('ENV') == 'production' else 'lax',
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRY_DAYS,
    )


def clear_refresh_cookie(response: Response):
    response.delete_cookie(
        key='refresh_token',
        httponly=True,
        secure=os.getenv('ENV') == 'production',
        samesite='None' if os.getenv('ENV') == 'production' else 'lax',
    )


async def check_consent(conn, user_id: str) -> bool:
    return await conn.fetchval(
        """
        SELECT
            EXISTS (SELECT 1 FROM user_legal_acceptances WHERE user_id = $1 AND document_type = 'terms')
            AND
            EXISTS (SELECT 1 FROM user_legal_acceptances WHERE user_id = $1 AND document_type = 'privacy_policy')
        """,
        user_id,
    )


async def verify_token(token: str) -> str | None:
    supabase = get_supabase()
    try:
        res = await supabase.auth.get_user(token)
        return res.user.id if res.user else None
    except Exception as _:
        return None
