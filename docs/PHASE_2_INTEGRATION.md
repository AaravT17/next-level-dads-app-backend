# Phase 2 integration — running each other's work

Two streams of work were built in parallel off the same commit and have now been
merged. This is the guide to getting the merged branch running, from either
side, given that our two Supabase projects are **not** in the same state.

Read the section for your side. The parts that apply to both are marked.

| | Finn's stream | Aarav's stream |
|---|---|---|
| Branches | `be/01`–`be/10`, `fe/01`–`fe/13`, merged to `phase-2-staging` | `feat/chats`, `feat/onboarding` |
| Now lives in | `integration/phase-2-merge` | `integration/phase-2-merge` |
| Migration | `20260901000000_phase_2_platform.sql` | `20260912000000_onboarding_overhaul.sql` |

---

## 1. Get the branch

Both repos have a branch called `integration/phase-2-merge` holding all four
merges. It is **local only** — nothing has been pushed.

```bash
# in each repo
git fetch origin
git switch integration/phase-2-merge
```

If you do not have it yet, whoever holds it pushes first:

```bash
git push -u origin integration/phase-2-merge
```

Both repos must move together. The WebSocket handshake, the event payload
shapes, and the `/api/chats/membership` endpoint changed on both sides at once —
an old frontend against a new backend will connect and then sit there with no
messages, because the socket closes on a rejected subprotocol.

---

## 2. Database

### What the migrations are

There is no migration runner in this repo. Migrations are applied by hand, in
timestamp order, before deploying code that depends on them.

```
db/migrations/
  20260628000000_moderation_center_support.sql              ← shared baseline
  20260701000000_user_preferences_and_legal_acceptances.sql ← shared baseline
  20260901000000_phase_2_platform.sql                       ← Finn's work
  20260912000000_onboarding_overhaul.sql                    ← Aarav's work
```

The two August files predate the fork and are already applied in both projects.
The two September files are the ones that matter here — one per stream,
deliberately kept apart so each of us can see exactly what the other is asking
our database to do.

`20260901000000_phase_2_platform.sql` is a consolidation of four migrations that
used to be separate (connection request notes, community invite messages,
community images, moderation audit trail). Since migrations are applied by hand
there is no ledger to contradict, so collapsing them is safe: applying the one
file is equivalent to having applied the four in order.

### Order does not matter

Both orderings were tested against a scratch Postgres built from the pre-merge
schema, and converge on an identical result. Run them in whichever order suits
you.

### Finn's migration — safe to re-run

`20260901000000_phase_2_platform.sql` is idempotent. Every `ADD COLUMN` uses
`IF NOT EXISTS`, the check constraint and the storage policy are guarded by
`DO` blocks, and the bucket insert is `ON CONFLICT DO NOTHING`. Running it
against a database that already has some or all of it prints `NOTICE ... skipping`
and changes nothing else.

**This is the one to point at a database whose state you are unsure of.**

What it adds:

- `connections.note` — the optional message on a connection request, plus a
  300-character check constraint.
- `messages.shared_community_id` — community invites ride the existing DM thread
  as an ordinary message with a community attached. Partial index alongside.
- `communities.image_url`, the `community-images` storage bucket, and a
  public-read policy on it.
- Moderation audit columns: `actioned_by` / `actioned_at` on `moderation_reports`
  and `user_reports`, `created_by` / `lifted_by` on `moderation_bans`,
  `actioned_by` on `moderation_filtered_messages`.

The moderation audit columns must go in **with** the backend code that writes
them — the admin routes write `actioned_by` unconditionally.

### Aarav's migration — read this before running it

`20260912000000_onboarding_overhaul.sql` is **not** idempotent and **deletes
production data**. It is wrapped in `BEGIN`/`COMMIT`, so a failure rolls back
cleanly and leaves the database untouched — but a success is not reversible.

Two destructive steps:

**It deletes every interest that is not in the curated list of 30**, and the
`user_interests` rows attached to them cascade away with it:

```sql
DELETE FROM interests WHERE slug IS NULL;
```

Before that it merges a handful of pairs (Food+Cooking, DIY+Home Projects,
Soccer→Sports, Running/Martial Arts→Fitness), remapping users onto the survivor.
Anything outside those merges and outside the curated 30 — deprecated interests
and any user-created ones — is dropped along with everyone's selection of it.

**It deletes every user in Quebec**, from `auth.users`, which cascades to
`public.users` and everything hanging off it:

```sql
DELETE FROM auth.users
WHERE id IN (SELECT id FROM users WHERE province = 'QC');
```

The migration notes this as a legal requirement (the product cannot operate in
QC). It is still an irreversible delete of real accounts.

Before running it against a database with real users:

```bash
# see what you are about to lose
psql "$DATABASE_URL" -c "SELECT count(*) FROM users WHERE province = 'QC';"
psql "$DATABASE_URL" -c "
  SELECT i.name, count(ui.user_id) AS users_affected
  FROM interests i LEFT JOIN user_interests ui ON ui.interest_id = i.id
  GROUP BY i.name ORDER BY users_affected DESC;"
```

Take a Supabase point-in-time backup first. Because it cannot be re-run, a
partial state is not a thing you can resume from — you restore and start over.

Re-running it after success fails immediately on
`column "slug" of relation "interests" already exists` and rolls back. That is
harmless, just not useful.

### Applying them

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/20260901000000_phase_2_platform.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/20260912000000_onboarding_overhaul.sql
```

`ON_ERROR_STOP=1` matters. Without it psql continues past a failed statement.

### Checking where a database currently stands

Neither project records which migrations have run, so probe for the objects:

```sql
SELECT
  (SELECT count(*) FROM information_schema.columns
    WHERE table_name='connections' AND column_name='note')          AS finn_notes,
  (SELECT count(*) FROM information_schema.columns
    WHERE table_name='communities' AND column_name='image_url')     AS finn_images,
  (SELECT count(*) FROM information_schema.columns
    WHERE table_name='moderation_bans' AND column_name='created_by') AS finn_audit,
  (SELECT count(*) FROM information_schema.columns
    WHERE table_name='interests' AND column_name='slug')            AS aarav_slugs,
  (SELECT count(*) FROM information_schema.columns
    WHERE table_name='users' AND column_name='kid_count')           AS aarav_profile;
```

`1` means applied, `0` means not. Finn's three can be brought up to date by just
re-running the file; Aarav's two cannot.

### Building a database from scratch

`db/schema.ddl` is the full current schema and has been updated to match — it now
reproduces byte-for-byte the same column set as applying both migrations to the
old schema. Use it for a fresh local database; use the migrations for one that
already has data.

---

## 3. Supabase project setup — both sides

Two storage buckets are required. Neither migration creates `avatars`; it
predates this work and should already exist.

| Bucket | Public | Created by |
|---|---|---|
| `avatars` | yes | pre-existing |
| `community-images` | yes | Finn's migration |

Uploads to both go through the backend's service-role client after an
admin/ownership check, so anon and authenticated writes stay closed. Only the
public-read policy is created by the migration. If you are setting up a fresh
Supabase project, confirm `avatars` exists and is public-read before testing
avatar upload.

---

## 4. Environment files

### Backend `.env`

`ENV`, `FRONTEND_BASE_URL` and `DATABASE_URL` are validated at import time — a
missing one raises at startup rather than silently changing behaviour, because
`IS_PRODUCTION` alone gates all rate limiting and the refresh cookie's `Secure`
flag.

| Variable | Required | New in this branch | Notes |
|---|---|---|---|
| `ENV` | yes | no | One of `production`, `development`, `test`. Validated. |
| `FRONTEND_BASE_URL` | yes | no | CORS origin and redirect target. |
| `DATABASE_URL` | yes | no | Supabase pooler URL, `?pgbouncer=true`. |
| `REDIS_URL` | yes | no | Now carries per-chat pub/sub, not just rate limits. |
| `SUPABASE_URL` | yes | no | |
| `SUPABASE_SECRET_KEY` | yes | no | Service-role key. Storage uploads use it. |
| `TRUSTED_PROXY_HOPS` | no | **yes** | Proxies in front of the app, counted from the right of `X-Forwarded-For`. Defaults to 1 in production, 0 otherwise. |
| `TRUSTED_CLIENT_IP_HEADER` | no | **yes** | Single-value client-IP header from the edge, preferred over `X-Forwarded-For`. |
| `LOG_LEVEL` | no | no | Defaults to `INFO`. |

Copy the current shape from `.env.example`. The two `TRUSTED_*` variables are the
only additions; both are optional and both default sensibly for local work, so an
existing local `.env` keeps working untouched.

**Redis is no longer optional in practice.** Chat used to fan out per user; it now
subscribes per chat (`chat:{id}`) and per user (`user:{id}`). Without Redis the
app starts but no message ever arrives at a second client.

```bash
brew services start redis     # or: docker run -p 6379:6379 redis
```

### Frontend `.env`

Unchanged by this work — no new variables on either branch.

```
VITE_ENV=development
VITE_FRONTEND_BASE_URL=http://localhost:3000
VITE_BACKEND_BASE_URL=http://localhost:8000
VITE_WEBSITE_BASE_URL=https://nextleveldads.ca
VITE_SUPABASE_URL=https://<project-id>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

One trap: `vite.config.ts` serves on port **3000**, and `VITE_FRONTEND_BASE_URL`
and the backend's `FRONTEND_BASE_URL` both assume that. If you change the dev
port, change all three or CORS will reject the socket.

---

## 5. Dependencies

### Backend

`requirements.txt` is unchanged on every branch. There is a **new**
`requirements-dev.txt` holding the test toolchain, kept out of the runtime file
so the deployed image does not carry it.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes -r requirements.txt
```

Python 3.11 — that is what CI pins.

### Frontend

`package.json` changed in ways that need a real install, not an incremental one:

- `@supabase/supabase-js` was replaced by `@supabase/auth-js`. Only the auth
  client was ever used, and the full SDK was a large part of the initial bundle.
  Every import in `src/` is already on `auth-js`.
- `vitest` was added, with `test` and `test:watch` scripts.

```bash
npm ci
```

Use `npm ci`, not `npm install` — the supabase swap means a stale `node_modules`
can resolve to the old package and typecheck against the wrong client. Node 22 is
what CI pins; 24 works locally.

---

## 6. Running it

```bash
# backend
source .venv/bin/activate
uvicorn main:app --reload --port 8000

# frontend
npm run dev            # serves on :3000
```

Order does not matter; the frontend retries the socket with backoff.

---

## 7. Verifying your setup

These are exactly what CI runs. If they pass locally, the branch is sound on
your machine.

```bash
# backend
ruff check app main.py tests
pytest -q                     # 134 tests
python -c "import main"

# frontend
npm run typecheck
npm run lint                  # zero warnings is the baseline
npm test                      # 50 tests
npm run build
```

Then the part no test covers — the two repos agreeing over the wire:

1. Log in. The socket should open and the server should send `{"type":"ws:ready"}`.
   Check the Network tab: the request carries `Sec-WebSocket-Protocol: bearer, <token>`
   and **no** `token` or `connection_id` query parameter.
2. Send a message from a second account. It should land live, and the unread
   badge should increment.
3. Log out. Open sockets should close with code 1008 rather than lingering.
4. Complete onboarding through to the edit-profile screen and confirm the new
   fields persist.

If step 1 shows the socket opening and closing immediately, the two repos are on
different commits — that is the subprotocol being rejected.

---

## 8. What changed in the code, and why yours may look different

Where the two streams disagreed, the merge kept one side deliberately. If you go
looking for your own code and find it rewritten, this is why.

**WebSocket transport — Finn's kept.** The token travels as a
`Sec-WebSocket-Protocol` offer rather than a query parameter, and the server
generates `connection_id` instead of accepting one from the client. The
`// TODO: Frontend should rotate connection IDs` in `feat/chats` is resolved by
this rather than ignored — a server-generated id cannot collide. The message rate
limit and the token-expiry close came along with it.

**Pub/sub architecture — Aarav's kept.** Per-chat Redis channels replaced the
per-user fan-out, `publish()` now takes `(channel, event)` and events are flat
rather than wrapped in a `{user_id, event_data}` envelope. Finn's session
revocation, malformed-payload guards and logging were re-applied on top of the
new structure rather than discarded. Message fan-out on `chat:{id}` also reaches
the sender's own other devices, which the per-user scheme had to exclude.

**Backend constants — Finn's path kept.** `app/common/config/constants.py`, not
`app/common/constants.py`. Both sides' additions are merged into the one file.
`app/common/types.py` is new and kept as is.

**Profile screens — Aarav's kept.** `MyProfile`, `ProfileDetail` and `YouPage`
are the onboarding versions, and `src/features/profile/components/` was deleted
with them. Two pieces of Finn's work rode on those screens and were carried back
because they are behaviour rather than visuals: the connect-request note dialog
on `ProfileDetail`, and the note render on `DadCard`.

**React contexts — Finn's split kept.** Each context is three files —
`XContext.ts` (the context object), `XProvider.tsx` (the component), `useX.ts`
(the hook) — because a module exporting both a component and a context opts out
of Fast Refresh. Aarav's provider logic was ported into `ChatProvider.tsx`;
imports move from `@/contexts/ChatContext` to `@/contexts/useChat`, and from
`@/contexts/AuthContext` to `@/contexts/useAuth`.

**Route imports — Finn's lazy loading kept.** `App.tsx` keeps `lazy(() => import(...))`
for every page. `OnboardingWelcome` was added to that set and chunks on its own.

**Upload hardening — Finn's kept, on Aarav's API shape.** Avatar upload stays on
its own `PUT /me/avatar` endpoint as the onboarding rewrite has it, but still
behind `read_capped_upload` and `assert_image_contents`.

---

## 9. Known gaps

- **`docs/pubsub_design.md`** benchmarks the handler as it was before the merge.
  The numbers stand; the code sample no longer matches, because the auth preamble
  now sits in front of it.
- **No migration ledger.** Nothing records what has been applied. The probe query
  in §2 is the substitute. Worth fixing properly before the next round of
  parallel work.
- **The backend test count moves with the source.** `test_sql_argument_counts`
  generates one case per literal-SQL call site, so 134 is not a fixed number —
  it dropped from 137 when the profile rewrite consolidated three queries. A
  change in the count is not by itself a failure.
