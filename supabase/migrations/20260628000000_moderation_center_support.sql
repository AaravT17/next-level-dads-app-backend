-- Community conversations, moderation, notifications, toxicity scores, and
-- admin moderation center support.
--
-- Consolidated from the split local migration files so this feature lands as
-- one schema change.

-- ── Community conversation tables ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  community_id UUID NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
  author_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  prompt_type TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  author_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_hearts (
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (conversation_id, user_id)
);

CREATE TABLE IF NOT EXISTS message_hearts (
  message_id UUID NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (message_id, user_id)
);

CREATE TABLE IF NOT EXISTS conversation_participants (
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  first_joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_active_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (conversation_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_community_activity
ON conversations (community_id, last_activity_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_created
ON conversation_messages (conversation_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_conversation_participants_user
ON conversation_participants (user_id);

-- ── Soft-delete flags and toxicity scores ─────────────────────────────────

ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS deleted_by_moderator BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE conversation_messages
  ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS toxicity_score DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS deleted_by_moderator BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE message_replies
  ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS toxicity_score DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS deleted_by_moderator BOOLEAN NOT NULL DEFAULT FALSE;

-- ── Moderation audit, reports, bans, and notifications ────────────────────

CREATE TABLE IF NOT EXISTS moderation_filtered_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_type TEXT NOT NULL CHECK (content_type IN ('conversation', 'message', 'reply')),
  content_id UUID NOT NULL,
  author_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
  community_id UUID REFERENCES communities(id) ON DELETE SET NULL,
  original_text TEXT NOT NULL,
  layer TEXT NOT NULL CHECK (layer IN ('profanity', 'hate_speech', 'report')),
  reason TEXT,
  score DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_moderation_filtered_author_created
ON moderation_filtered_messages (author_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_moderation_filtered_content
ON moderation_filtered_messages (content_type, content_id);

CREATE TABLE IF NOT EXISTS moderation_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_type TEXT NOT NULL CHECK (content_type IN ('conversation', 'message', 'reply')),
  content_id UUID NOT NULL,
  reporter_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'reviewed', 'dismissed', 'actioned')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (content_type, content_id, reporter_id)
);

CREATE INDEX IF NOT EXISTS idx_moderation_reports_status_created
ON moderation_reports (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_moderation_reports_content
ON moderation_reports (content_type, content_id);

CREATE TABLE IF NOT EXISTS moderation_bans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_moderation_bans_user_expires
ON moderation_bans (user_id, expires_at DESC);

CREATE TABLE IF NOT EXISTS moderation_notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('content_removed', 'temporary_ban')),
  content_type TEXT CHECK (content_type IN ('conversation', 'message', 'reply')),
  content_id UUID,
  layer TEXT CHECK (layer IN ('profanity', 'hate_speech', 'report')),
  reason TEXT,
  message TEXT NOT NULL,
  is_read BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_moderation_notifications_user_unread
ON moderation_notifications (user_id, is_read, created_at DESC);

-- ── Admin moderation support ──────────────────────────────────────────────

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS user_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reported_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  reporter_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'reviewed', 'dismissed', 'actioned')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_reports_unique_pair
ON user_reports (reported_id, reporter_id);

CREATE INDEX IF NOT EXISTS idx_user_reports_status_created
ON user_reports (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_reports_reported_created
ON user_reports (reported_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversations_author_created
ON conversations (author_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_author_created
ON conversation_messages (author_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_message_replies_author_created
ON message_replies (author_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_message_replies_message_created
ON message_replies (message_id, created_at ASC);

-- ── Row-level security ────────────────────────────────────────────────────
--
-- All application data access goes through the FastAPI backend, which connects
-- with a privileged Postgres role that bypasses RLS. Enabling RLS with no
-- permissive policy denies the Supabase `anon`/`authenticated` roles any direct
-- PostgREST access, closing the path where a client could PATCH its own
-- `users.is_admin = true` or read removed-content `original_text` using the
-- shipped publishable key. Re-enabling an already-enabled table is a no-op.

ALTER TABLE public.users                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_messages         ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_replies               ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_hearts           ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_hearts                ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_participants     ENABLE ROW LEVEL SECURITY;
ALTER TABLE moderation_filtered_messages  ENABLE ROW LEVEL SECURITY;
ALTER TABLE moderation_reports            ENABLE ROW LEVEL SECURITY;
ALTER TABLE moderation_bans               ENABLE ROW LEVEL SECURITY;
ALTER TABLE moderation_notifications      ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_reports                  ENABLE ROW LEVEL SECURITY;
