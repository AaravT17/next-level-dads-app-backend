-- Notification centre: persistent notifications and per-user read/clear state.

BEGIN;

-- ── Notifications ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL CHECK (type IN ('connection_request', 'connection_accepted', 'chat_added')),
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Primary lookup: fetch a user's notifications in reverse-chronological order.
-- Also used for the unread count query (COUNT where created_at > last_read_at).
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
ON notifications (user_id, created_at DESC);

-- ── User notification state ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_notification_state (
    user_id         UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    last_read_at    TIMESTAMPTZ,
    last_cleared_at TIMESTAMPTZ
);

-- ── Row-level security ──────────────────────────────────────────────────────

ALTER TABLE notifications             ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_notification_state   ENABLE ROW LEVEL SECURITY;

COMMIT;
