# ruff: noqa: E402
from dotenv import load_dotenv

load_dotenv()

from app.common.config.logging import configure_logging

configure_logging()

from fastapi import FastAPI
from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.interests.router import router as interests_router
from app.modules.communities.router import router as communities_router, conversations_router, messages_router, replies_router
from app.modules.events.router import router as events_router
from app.modules.connections.router import router as connections_router
from app.modules.moderation.router import router as moderation_router
from app.modules.admin.router import router as admin_router
from app.modules.chats.router import router as chats_router
from app.modules.ws.router import router as ws_router
from app.common.config.redis import init_redis, close_redis, get_redis
from app.common.config.pubsub import init_pubsub, close_pubsub
from fastapi.middleware.cors import CORSMiddleware
import os
from contextlib import asynccontextmanager
from app.common.config.supabase import init_supabase
import asyncpg
from fastapi_limiter import FastAPILimiter
from app.common.config.constants import IS_PRODUCTION
from app.modules.moderation import profanity_filter


@asynccontextmanager
async def lifespan(app: FastAPI):
    if IS_PRODUCTION and not profanity_filter.is_available():
        # The toxicity layer is a stub, so the wordlist is the only filtering
        # that runs. Booting without it would serve every post unmoderated with
        # nothing but a warning line to say so -- better to not come up at all.
        raise RuntimeError(
            'better-profanity failed to load; it is the only active moderation '
            'layer. Refusing to start in production without content filtering.'
        )
    try:
        await init_supabase()
        init_redis()
        await init_pubsub()
        app.state.pool = await asyncpg.create_pool(
            os.getenv('DATABASE_URL'),
            ssl='require',
            statement_cache_size=0,
        )
        if IS_PRODUCTION:
            await FastAPILimiter.init(get_redis())
    except Exception as _:
        await close_pubsub()
        await close_redis()
        pool = getattr(app.state, 'pool', None)
        if pool:
            await pool.close()
        raise SystemExit(1)
    yield
    await close_pubsub()
    if IS_PRODUCTION:
        await FastAPILimiter.close()
    await close_redis()
    await app.state.pool.close()


# The interactive docs enumerate every route and schema, including the admin and
# moderation surfaces. Useful locally, not something to publish.
app = FastAPI(
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else '/docs',
    redoc_url=None if IS_PRODUCTION else '/redoc',
    openapi_url=None if IS_PRODUCTION else '/openapi.json',
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv('FRONTEND_BASE_URL')],
    # Dev only. Loopback has three spellings -- localhost, 127.0.0.1 and [::1] --
    # and which one the browser sends as Origin depends on how the page was
    # opened, not on any choice the app makes. Pinning to a single spelling
    # rejects the other two as cross-origin. Production stays pinned to
    # FRONTEND_BASE_URL, where the origin is a real host and not ambiguous.
    allow_origin_regex=None if IS_PRODUCTION else r'http://(localhost|127\.0\.0\.1|\[::1\]):\d+',
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(interests_router)
app.include_router(communities_router)
app.include_router(conversations_router)
app.include_router(messages_router)
app.include_router(replies_router)
app.include_router(events_router)
app.include_router(connections_router)
app.include_router(moderation_router)
app.include_router(admin_router)
app.include_router(chats_router)
app.include_router(ws_router)
