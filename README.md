# Next Level Dads Backend

FastAPI backend for Next Level Dads. It provides authentication session handling, profiles, dads discovery, communities, community conversations, events, connections, chats, moderation, admin tools, realtime WebSockets, uploads, and rate limiting.

The backend is organized by domain modules under `app/modules` with shared infrastructure under `app/common`.

## Stack

- Python 3.11
- FastAPI
- asyncpg
- Supabase Python client
- Redis
- Redis Pub/Sub for realtime fan-out
- fastapi-limiter
- PyJWT
- better-profanity
- Uvicorn
- Ruff
- Pytest

## Main Features

- Auth: register, login, OAuth session exchange, refresh-token cookie, logout.
- Users: profile setup, profile updates, avatar uploads, dads discovery, current-user data.
- Connections: connection requests, request notes, incoming/outgoing request state.
- Communities: browse, create, join, leave, member lists, community images, community invites.
- Conversations: community posts, replies, hearts, sorting, pagination, cross-community feed.
- Events: event discovery and detail endpoints.
- Chats: direct/group chats, participants, group management, messages, read state.
- WebSockets: authenticated realtime delivery for chat events and session revocation.
- Moderation: content reporting, automatic filtering, temporary bans, admin action audit fields.
- Admin: report review, filtered-message review, bans, ban lifts/dismissals.
- Security: production rate limits, trusted proxy IP parsing, upload caps, image content checks, production docs disabled.

## Local Setup

Create and activate a virtual environment:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
```

Install runtime dependencies:

```sh
pip install -r requirements.txt
```

For tests and linting, install the development set instead:

```sh
pip install -r requirements-dev.txt
```

Create a local environment file:

```sh
cp .env.example .env
```

Fill in the database, Redis, Supabase, and frontend origin values.

Run the API:

```sh
uvicorn main:app --reload --port 8000
```

In non-production environments, interactive docs are available at:

- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`
- `http://localhost:8000/openapi.json`

Those routes are disabled when `ENV=production`.

## Environment Variables

See `.env.example` for the full list.

Required:

- `ENV`: one of `development`, `production`, or `test`.
- `FRONTEND_BASE_URL`: exact frontend browser origin for CORS and cookies.
- `DATABASE_URL`: Postgres connection string.
- `REDIS_URL`: Redis connection string.
- `SUPABASE_URL`: Supabase project URL.
- `SUPABASE_SECRET_KEY`: Supabase service/secret key used by the backend.

Optional:

- `TRUSTED_PROXY_HOPS`: number of trusted proxy hops to read from the right of `X-Forwarded-For`; defaults to `1` in production and `0` otherwise.
- `TRUSTED_CLIENT_IP_HEADER`: a single-value trusted client IP header set by the edge, such as `True-Client-IP` or `CF-Connecting-IP`.

The app validates key configuration at import/startup. A missing or misspelled `ENV` is expected to fail fast.

## Commands

```sh
uvicorn main:app --reload --port 8000    # Local API server
ruff check app main.py tests             # Lint
pytest -q                                # Unit tests
python -c "import main"                  # Import check
```

## CI

GitHub Actions runs on pull requests and pushes to `main`:

```sh
pip install -r requirements-dev.txt
ruff check app main.py tests
pytest -q
python -c "import main"
```

The CI environment does not use real secrets. `tests/conftest.py` supplies placeholder values, and the current tests do not reach external services.

## Project Structure

```text
app/
  common/
    config/          environment, logging, Redis, Supabase, Pub/Sub
    dependencies/    auth, database, rate-limit dependencies
    utils/           shared errors and upload helpers
    ws/              shared WebSocket connection manager
  modules/
    admin/           admin report/ban/filter review routes
    auth/            auth routes, models, service, token/session utilities
    chats/           chat routes, models, service
    communities/     communities, conversations, messages, replies, invites, images
    connections/     connection request routes and status helpers
    events/          events routes and service
    interests/       interests routes and utilities
    moderation/      reports, filters, bans, audit helpers
    users/           profile and dad discovery routes
    ws/              WebSocket auth and router
db/
  migrations/        SQL migrations
  schema.ddl         current schema reference
tests/               pure unit tests and import-safe checks
main.py              FastAPI app, lifespan, middleware, router registration
```

## Database and Migrations

Migrations live in `db/migrations`. The current branch adds migrations for:

- Connection request notes.
- Community invite messages.
- Community images and the `community-images` bucket.
- Moderation audit fields.

There is no migration runner in this repo yet. Apply migrations manually in the target database before deploying code that depends on new columns.

The moderation audit migration must be applied with the backend code that writes `actioned_by`, `actioned_at`, `created_by`, and `lifted_by`.

## Realtime and WebSockets

The WebSocket route authenticates during the browser handshake through the `Sec-WebSocket-Protocol` offer. Access tokens should not be sent in the query string.

Connections are tracked server-side. Logout publishes a session revocation event through Redis so live sockets for that user close promptly. Token expiry also closes sockets with a policy-violation code so the frontend can refresh and reconnect.

## Frontend Pairing

Some backend changes are paired with frontend changes and should deploy first:

- `GET /api/conversations` before the frontend cross-community feed.
- `GET /api/users/me/conversations` before the Home resume rail.
- Connection request notes before the request-note UI.
- `POST /api/communities/{id}/invites` before community invite UI.
- `PUT` and `DELETE /api/communities/{id}/image` before enabling community photo editing.
- WebSocket subprotocol auth at the same time as the frontend WebSocket handshake change.

For stacked PR notes and merge ordering, see `../pr-notes/stacked-prs.md` from the workspace root.

## Production Notes

- `ENV=production` enables production-only behavior such as route-level rate limiting and secure cookie assumptions.
- Production refuses to start if the profanity filter is unavailable.
- API docs are disabled in production.
- Upload endpoints cap file size and verify image signatures.
- Internal validation failures are returned as generic 500 responses rather than exposing database or Pydantic details.
