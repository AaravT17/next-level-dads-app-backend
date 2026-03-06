from fastapi import Request
from typing import AsyncGenerator
import asyncpg


async def get_db(request: Request) -> AsyncGenerator[asyncpg.Connection, None]:
    async with request.app.state.pool.acquire() as conn:
        yield conn
