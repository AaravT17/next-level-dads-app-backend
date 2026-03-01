from supabase import acreate_client as async_create_client, AsyncClient
import os

supabase_client: AsyncClient | None = None

SUPABASE_URL = os.getenv("SUPABASE_URL", None)
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", None)


async def init_supabase():
    global supabase_client
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        raise ValueError(
            "Supabase URL and Secret Key must be set in environment variables."
        )
    supabase_client = await async_create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


def get_supabase() -> AsyncClient:
    if supabase_client is None:
        raise RuntimeError("Supabase client not initialized.")
    return supabase_client
