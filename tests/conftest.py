"""Test-wide environment setup.

`app.common.config.constants` validates required environment variables at import
time, so they must exist before any app module is imported — including for pure
unit tests that never touch a service.

A local .env supplies real values when present. CI has none, so placeholders
stand in; nothing here connects to anything.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

# Forced rather than defaulted, so a run is identical whatever a developer's
# .env happens to say.
os.environ['ENV'] = 'test'

os.environ.setdefault('FRONTEND_BASE_URL', 'http://localhost:5173')
os.environ.setdefault('DATABASE_URL', 'postgresql://localhost/nld_test')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379')
os.environ.setdefault('SUPABASE_URL', 'https://test.supabase.co')
os.environ.setdefault('SUPABASE_SECRET_KEY', 'test-secret-key')
