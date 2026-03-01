from fastapi import APIRouter, HTTPException, status, Request, Response, Depends
from supabase_auth.errors import AuthApiError
from app.config.supabase import get_supabase
from app.models.auth import (
    RegisterRequest,
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    OAuthSessionRequest,
)
import os
from app.dependencies.auth import get_current_access_token
from app.utils.auth import set_refresh_cookie, clear_refresh_cookie

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
async def register_user(credentials: RegisterRequest):
    supabase = get_supabase()
    try:
        await supabase.auth.sign_up(
            {
                "email": credentials.email,
                "password": credentials.password,
                "options": {
                    "email_redirect_to": f"{os.getenv('FRONTEND_BASE_URL')}/verify-email"
                },
            }
        )
        return {
            "detail": "User registered successfully! Please verify your email before logging in."
        }
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later.",
        )


@router.post("/login", response_model=LoginResponse)
async def login_user(credentials: LoginRequest, response: Response):
    supabase = get_supabase()
    try:
        res = await supabase.auth.sign_in_with_password(
            {
                "email": credentials.email,
                "password": credentials.password,
            }
        )
        set_refresh_cookie(response, res.session.refresh_token)
        return {"access_token": res.session.access_token}
    except AuthApiError as e:
        if e.status == 400 and "invalid login credentials" in e.message.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials."
            )
        if e.status == 400 and "email not confirmed" in e.message.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Please verify your email before logging in.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later.",
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later.",
        )


@router.post("/oauth/session", response_model=LoginResponse)
async def set_oauth_session(credentials: OAuthSessionRequest, response: Response):
    supabase = get_supabase()
    try:
        user = await supabase.auth.get_user(credentials.access_token)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token."
            )
        set_refresh_cookie(response, credentials.refresh_token)
        return {"access_token": credentials.access_token}
    except AuthApiError as _:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token."
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later.",
        )


@router.post("/logout")
async def logout_user(
    response: Response, access_token: str = Depends(get_current_access_token)
):
    supabase = get_supabase()
    try:
        await supabase.auth.admin.sign_out(access_token)
    except Exception as _:
        pass  # we want to clear the cookie even if the sign out fails for some reason
    clear_refresh_cookie(response)
    return {"detail": "Logged out successfully."}


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(request: Request, response: Response):
    supabase = get_supabase()
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token."
        )

    try:
        res = await supabase.auth.refresh_session(refresh_token)
        set_refresh_cookie(response, res.session.refresh_token)
        return {"access_token": res.session.access_token}
    except AuthApiError as _:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )
    except Exception as _:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later.",
        )
