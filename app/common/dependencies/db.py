from fastapi import Request
from typing import AsyncGenerator
import asyncpg


async def get_db(request: Request) -> AsyncGenerator[asyncpg.Connection, None]:
    async with request.app.state.pool.acquire() as conn:
        yield conn


def get_pool(request: Request) -> asyncpg.Pool:
    """The shared connection pool, for work that outlives the request.

    Background tasks run after the response is sent and the request-scoped
    connection from `get_db` is already released, so they must acquire their
    own connection from the pool.
    """
    return request.app.state.pool
