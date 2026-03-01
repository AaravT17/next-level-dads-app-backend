# ruff: noqa: E402
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from app.routers.auth import router as auth_router
from app.routers.users import router as users_router
from fastapi.middleware.cors import CORSMiddleware
import os
from contextlib import asynccontextmanager
from app.config.supabase import init_supabase


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_supabase()
    except Exception as _:
        raise SystemExit(1)
    yield


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
