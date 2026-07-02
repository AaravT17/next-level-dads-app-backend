# ruff: noqa: E402
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from app.routers.auth import router as auth_router
from app.routers.users import router as users_router
from app.routers.interests import router as interests_router
from app.routers.communities import router as communities_router, conversations_router, messages_router, replies_router
from app.routers.events import router as events_router
from app.routers.connections import router as connections_router
from app.routers.moderation import router as moderation_router
from app.routers.admin import router as admin_router
from app.routers.chats import router as chats_router
from app.routers.ws import router as ws_router
from app.config.redis import init_redis, close_redis
from app.ws.pubsub import init_pubsub, close_pubsub
from fastapi.middleware.cors import CORSMiddleware
import os
from contextlib import asynccontextmanager
from app.config.supabase import init_supabase
import asyncio
import asyncpg


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_supabase()
        init_redis()
        await init_pubsub()
        app.state.pool = await asyncpg.create_pool(
            os.getenv('DATABASE_URL'),
            ssl='require',
            statement_cache_size=0,
        )
    except Exception as _:
        await close_pubsub()
        await close_redis()
        raise SystemExit(1)
    yield
    await close_pubsub()
    await close_redis()
    await app.state.pool.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv('FRONTEND_BASE_URL')],
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
