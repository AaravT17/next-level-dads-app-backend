import os
from fastapi import HTTPException, Request, status
from fastapi_limiter.depends import RateLimiter


# --- Helper functions ---
async def ip_key(request: Request) -> str:
    """Return the IP address of the client making the request."""
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.client.host


async def user_id_key(request: Request) -> str:
    """Return the user_id of the user making the request, or the IP address if the user_id is not available."""
    user_id = getattr(request.state, 'user_id', None)
    if user_id:
        return str(user_id)
    ip = await ip_key(request)
    return ip


async def rate_limit_exceeded_callback(*__args):
    """Raise an HTTPException with status code 429 (Too Many Requests) when the rate limit is exceeded."""
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail='Too many requests. Please try again later.',
    )


def is_production() -> bool:
    return os.getenv('ENV') == 'production'


# --- Rate limiters ---
# Auth endpoints are rate limited by IP address, while other endpoints are rate limited by user_id


# --- Auth ---
def RegisterLimiter():
    return RateLimiter(times=5, hours=1, identifier=ip_key, callback=rate_limit_exceeded_callback)


def LoginLimiter():
    return RateLimiter(times=10, minutes=15, identifier=ip_key, callback=rate_limit_exceeded_callback)


def RefreshLimiter():
    return RateLimiter(times=30, minutes=15, identifier=ip_key, callback=rate_limit_exceeded_callback)


def OAuthSessionLimiter():
    return RateLimiter(times=10, minutes=15, identifier=ip_key, callback=rate_limit_exceeded_callback)


# --- Users ---
def CreateProfileLimiter():
    return RateLimiter(times=5, hours=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


def DiscoverProfilesLimiter():
    return RateLimiter(times=60, minutes=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


def UpdateAvatarLimiter():
    return RateLimiter(times=10, hours=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


def UpdateProfileLimiter():
    return RateLimiter(times=20, hours=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


# --- Communities ---
def CreateCommunityLimiter():
    return RateLimiter(times=20, hours=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


def CreateConversationLimiter():
    return RateLimiter(times=20, hours=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


def PostMessageLimiter():
    return RateLimiter(times=60, minutes=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


def PostReplyLimiter():
    return RateLimiter(times=60, minutes=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


# --- Chats ---
def CreateChatLimiter():
    return RateLimiter(times=10, minutes=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


def SendChatMessageLimiter():
    return RateLimiter(times=60, minutes=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


# --- Connections ---
def SendConnectionRequestLimiter():
    return RateLimiter(times=50, hours=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


# --- Moderation ---
def ReportContentLimiter():
    return RateLimiter(times=20, hours=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)


def ReportUserLimiter():
    return RateLimiter(times=10, hours=1, identifier=user_id_key, callback=rate_limit_exceeded_callback)
