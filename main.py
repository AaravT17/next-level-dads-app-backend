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
from fastapi.middleware.cors import CORSMiddleware
import os
from contextlib import asynccontextmanager
from app.config.supabase import init_supabase
from app.moderation.toxicity import warmup as warmup_moderation
import asyncio
import asyncpg


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_supabase()
        app.state.pool = await asyncpg.create_pool(
            os.getenv("DATABASE_URL"),
            ssl="require",
            statement_cache_size=0,
        )
    except Exception as _:
        raise SystemExit(1)
    # Load the toxicity model in the background so it's ready for the first
    # post without blocking startup.
    asyncio.create_task(warmup_moderation())
    yield
    await app.state.pool.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_BASE_URL")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
