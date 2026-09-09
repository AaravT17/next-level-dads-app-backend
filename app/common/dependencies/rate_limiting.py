from math import ceil
from typing import Awaitable, Callable

from fastapi import HTTPException, Request, status
from fastapi_limiter.depends import RateLimiter

from app.common.config.constants import TRUSTED_CLIENT_IP_HEADER, TRUSTED_PROXY_HOPS

KeyFunc = Callable[[Request], Awaitable[str]]


# --- Helper functions ---
def _client_ip(request: Request) -> str:
    """The caller's IP, taking only the hops we actually trust.

    `X-Forwarded-For` is a client-writable header: anything the caller sends
    arrives at the left of the list, and our own proxies append to the right.
    Reading the leftmost entry therefore reads the attacker's value, which
    hands out a fresh rate-limit bucket per request and defeats the limiter
    entirely. We count TRUSTED_PROXY_HOPS in from the right instead, so only
    the entries our infrastructure appended can be believed.

    A single-value header set by the edge (Render's True-Client-IP,
    Cloudflare's CF-Connecting-IP) is better still when one is configured,
    because it cannot be extended by the client at all.
    """
    if TRUSTED_CLIENT_IP_HEADER:
        edge_ip = request.headers.get(TRUSTED_CLIENT_IP_HEADER)
        if edge_ip:
            return edge_ip.strip()

    if TRUSTED_PROXY_HOPS > 0:
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            hops = [hop.strip() for hop in forwarded_for.split(',') if hop.strip()]
            if hops:
                # With one trusted proxy the client IP is the last entry — the one
                # that proxy appended. With two, the second to last, and so on.
                return hops[max(0, len(hops) - TRUSTED_PROXY_HOPS)]

    return request.client.host if request.client else 'unknown'


async def ip_key(request: Request) -> str:
    """Return the IP address of the client making the request."""
    return _client_ip(request)


async def user_id_key(request: Request) -> str:
    """Return the user_id of the user making the request, or the IP address if the user_id is not available."""
    user_id = getattr(request.state, 'user_id', None)
    if user_id:
        return str(user_id)
    return _client_ip(request)


def _scoped(name: str, base: KeyFunc) -> KeyFunc:
    """Namespace a limiter's Redis key so limiters cannot share a bucket.

    fastapi-limiter builds its key from the index of the matching route, found
    by comparing `route.path` against `request.scope['path']`. Those are the
    template and the concrete path, so for any route with a path parameter they
    never match and the index stays 0 — collapsing every parameterised route's
    limiter onto one key per caller. The window is then opened by whichever
    limiter fired first and never refreshed, so ordinary chatting exhausts the
    hourly image and invite budgets and stays 429 for the rest of the hour.

    Folding the limiter's own name into the identifier gives each one its own
    key regardless of what the library computes.
    """

    async def identifier(request: Request) -> str:
        return f'{name}:{await base(request)}'

    return identifier


async def rate_limit_exceeded_callback(request: Request, response, pexpire: int):
    """Raise an HTTPException with status code 429 (Too Many Requests) when the rate limit is exceeded."""
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail='Too many requests. Please try again later.',
        # pexpire is the remaining window in ms. Without this the client has no
        # way to know when to retry and tends to hammer the endpoint.
        headers={'Retry-After': str(ceil(pexpire / 1000))},
    )


def _limiter(name: str, base: KeyFunc, **window) -> RateLimiter:
    return RateLimiter(
        identifier=_scoped(name, base),
        callback=rate_limit_exceeded_callback,
        **window,
    )


# --- Rate limiters ---
# Auth endpoints are rate limited by IP address, while other endpoints are rate limited by user_id


# --- Auth ---
def RegisterLimiter():
    return _limiter('register', ip_key, times=5, hours=1)


def LoginLimiter():
    return _limiter('login', ip_key, times=10, minutes=15)


def RefreshLimiter():
    return _limiter('refresh', ip_key, times=30, minutes=15)


def OAuthSessionLimiter():
    return _limiter('oauth_session', ip_key, times=10, minutes=15)


# --- Users ---
def CreateProfileLimiter():
    return _limiter('create_profile', user_id_key, times=5, hours=1)


def DiscoverProfilesLimiter():
    return _limiter('discover_profiles', user_id_key, times=60, minutes=1)


def UpdateAvatarLimiter():
    return _limiter('update_avatar', user_id_key, times=10, hours=1)


def UpdateProfileLimiter():
    return _limiter('update_profile', user_id_key, times=20, hours=1)


# --- Communities ---
def CreateCommunityLimiter():
    return _limiter('create_community', user_id_key, times=20, hours=1)


def UpdateCommunityImageLimiter():
    return _limiter('update_community_image', user_id_key, times=10, hours=1)


def CreateConversationLimiter():
    return _limiter('create_conversation', user_id_key, times=20, hours=1)


def PostMessageLimiter():
    return _limiter('post_message', user_id_key, times=60, minutes=1)


def PostReplyLimiter():
    return _limiter('post_reply', user_id_key, times=60, minutes=1)


def InviteToCommunityLimiter():
    return _limiter('invite_to_community', user_id_key, times=20, hours=1)


# --- Chats ---
def CreateChatLimiter():
    return _limiter('create_chat', user_id_key, times=10, minutes=1)


def SendChatMessageLimiter():
    return _limiter('send_chat_message', user_id_key, times=60, minutes=1)


# --- Connections ---
def SendConnectionRequestLimiter():
    return _limiter('send_connection_request', user_id_key, times=50, hours=1)


# --- Moderation ---
def ReportContentLimiter():
    return _limiter('report_content', user_id_key, times=20, hours=1)


def ReportUserLimiter():
    return _limiter('report_user', user_id_key, times=10, hours=1)
