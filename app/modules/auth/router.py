from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from app.modules.auth.models import (
    RegisterRequest,
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    OAuthSessionRequest,
)
from app.common.dependencies.auth import get_current_access_token
import app.modules.auth.service as auth_service
from app.common.config.constants import IS_PRODUCTION
from app.common.dependencies.rate_limiting import (
    RegisterLimiter,
    LoginLimiter,
    RefreshLimiter,
    OAuthSessionLimiter,
)


router = APIRouter(prefix='/api/auth', tags=['auth'])


@router.post('/register', dependencies=[Depends(RegisterLimiter())] if IS_PRODUCTION else [])
async def register_user(credentials: RegisterRequest):
    await auth_service.register(credentials.email, credentials.password)
    return {'detail': 'User registered successfully! Please verify your email before logging in.'}


@router.post('/login', response_model=LoginResponse, dependencies=[Depends(LoginLimiter())] if IS_PRODUCTION else [])
async def login_user(credentials: LoginRequest, response: Response):
    access_token = await auth_service.login(credentials.email, credentials.password, response)
    return {'access_token': access_token}


@router.post(
    '/oauth/session',
    response_model=LoginResponse,
    dependencies=[Depends(OAuthSessionLimiter())] if IS_PRODUCTION else [],
)
async def create_session_from_oauth(credentials: OAuthSessionRequest, response: Response):
    access_token = await auth_service.create_session_from_oauth(credentials.access_token, credentials.refresh_token, response)
    return {'access_token': access_token}


@router.post('/logout')
async def logout_user(response: Response, access_token: str = Depends(get_current_access_token)):
    await auth_service.logout(access_token, response)
    return {'detail': 'Logged out successfully.'}


@router.post(
    '/refresh', response_model=RefreshResponse, dependencies=[Depends(RefreshLimiter())] if IS_PRODUCTION else []
)
async def refresh_session(request: Request, response: Response):
    refresh_token = request.cookies.get('refresh_token')
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing refresh token.')
    access_token = await auth_service.refresh_session(refresh_token, response)
    return {'access_token': access_token}
