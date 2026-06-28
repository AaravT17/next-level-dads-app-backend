-- ─────────────────────────────────────────────────────────────────────────────
-- Next Level Dads – Full Database Schema
-- ─────────────────────────────────────────────────────────────────────────────


-- ── Users ─────────────────────────────────────────────────────────────────────

CREATE TABLE public.users (
    id              UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    age             INTEGER,
    date_of_birth   DATE,
    city            TEXT NOT NULL,
    province        VARCHAR(2) NOT NULL,
    about           TEXT NOT NULL,
    avatar_url      TEXT,
    is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ── Interests ─────────────────────────────────────────────────────────────────

CREATE TABLE public.interests (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name)
);


-- ── User Interests ────────────────────────────────────────────────────────────

CREATE TABLE public.user_interests (
    user_id     UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    interest_id UUID NOT NULL REFERENCES public.interests(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, interest_id)
);


-- ── User Children ─────────────────────────────────────────────────────────────

CREATE TABLE public.user_children (
    user_id   UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    age_range TEXT NOT NULL,
    PRIMARY KEY (user_id, age_range)
);


-- ── User Profiles (View) ──────────────────────────────────────────────────────

CREATE VIEW public.user_profiles WITH (security_invoker = on) AS
SELECT
    u.id,
    u.name,
    COALESCE(DATE_PART('year', AGE(u.date_of_birth))::int, u.age) AS age,
    u.date_of_birth,
    u.city,
    u.province,
    u.about,
    u.avatar_url,
    u.created_at,
    array_agg(DISTINCT i.name)     AS interests,
    array_agg(DISTINCT uc.age_range) AS children
FROM public.users u
LEFT JOIN public.user_interests ui ON u.id = ui.user_id
LEFT JOIN public.interests i       ON ui.interest_id = i.id
LEFT JOIN public.user_children uc  ON u.id = uc.user_id
GROUP BY u.id;


-- ── Connections ───────────────────────────────────────────────────────────────

CREATE TABLE connections (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requesting_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requested_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status        TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'blocked')),
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT no_self_connection CHECK (requesting_id != requested_id)
);

CREATE UNIQUE INDEX unique_pair ON connections (
    LEAST(requesting_id, requested_id),
    GREATEST(requesting_id, requested_id)
);


-- ── Communities ───────────────────────────────────────────────────────────────

CREATE TABLE communities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    created_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);


-- ── Community Members ─────────────────────────────────────────────────────────

CREATE TABLE community_members (
    community_id UUID REFERENCES communities(id) ON DELETE CASCADE,
    user_id      UUID REFERENCES users(id) ON DELETE CASCADE,
    role         TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    joined_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (community_id, user_id)
);


-- ── Events ────────────────────────────────────────────────────────────────────

CREATE TABLE events (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  VARCHAR(100) NOT NULL,
    description           VARCHAR(1000),
    type                  TEXT NOT NULL CHECK (type IN ('local', 'virtual')),
    starts_at             TIMESTAMPTZ NOT NULL,
    ends_at               TIMESTAMPTZ,
    location              VARCHAR(500) NOT NULL,
    latitude              FLOAT8,
    longitude             FLOAT8,
    hosted_by_user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    hosted_by_org_name    VARCHAR(100),
    hosted_by_community_id UUID REFERENCES communities(id) ON DELETE SET NULL,
    contact_email         VARCHAR(254),
    contact_phone         VARCHAR(20),
    price_cad             NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    created_by            UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at            TIMESTAMPTZ DEFAULT now()
);


-- ── Event Attendees ───────────────────────────────────────────────────────────

CREATE TABLE event_attendees (
    event_id  UUID REFERENCES events(id) ON DELETE CASCADE,
    user_id   UUID REFERENCES users(id) ON DELETE CASCADE,
    joined_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (event_id, user_id)
);


-- ── Chats ─────────────────────────────────────────────────────────────────────

CREATE TABLE chats (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type       TEXT NOT NULL CHECK (type IN ('dm', 'group')),
    name       TEXT,
    dm_user_1  UUID REFERENCES users(id) ON DELETE CASCADE,
    dm_user_2  UUID REFERENCES users(id) ON DELETE CASCADE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX ON chats (
    LEAST(dm_user_1, dm_user_2),
    GREATEST(dm_user_1, dm_user_2)
) WHERE type = 'dm';

CREATE INDEX ON chats (updated_at, id);


-- ── Chat Participants ─────────────────────────────────────────────────────────

CREATE TABLE chat_participants (
    chat_id      UUID REFERENCES chats(id) ON DELETE CASCADE,
    user_id      UUID REFERENCES users(id) ON DELETE CASCADE,
    joined_at    TIMESTAMPTZ DEFAULT now(),
    last_read_at TIMESTAMPTZ,
    is_admin     BOOLEAN DEFAULT false,
    PRIMARY KEY (chat_id, user_id)
);

CREATE INDEX ON chat_participants (user_id);


-- ── Messages ──────────────────────────────────────────────────────────────────

CREATE TABLE messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id     UUID REFERENCES chats(id) ON DELETE CASCADE,
    sender_id   UUID REFERENCES users(id) ON DELETE SET NULL,
    reply_to_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    content     TEXT NOT NULL,
    edited_at   TIMESTAMPTZ,
    is_deleted  BOOLEAN DEFAULT false,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON messages (chat_id, created_at);
CREATE INDEX ON messages (reply_to_id);

CREATE OR REPLACE FUNCTION bump_chat_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE chats SET updated_at = NOW() WHERE id = NEW.chat_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER bump_chat_updated_at
AFTER INSERT ON messages
FOR EACH ROW EXECUTE FUNCTION bump_chat_updated_at();


-- ── Last Messages (View) ──────────────────────────────────────────────────────

CREATE VIEW public.last_messages WITH (security_invoker = on) AS
SELECT DISTINCT ON (m.chat_id)
    m.chat_id,
    m.id,
    m.content,
    m.sender_id,
    m.created_at,
    m.is_deleted,
    u.name AS sender_name
FROM messages m
LEFT JOIN users u ON u.id = m.sender_id
ORDER BY m.chat_id, m.created_at DESC;


-- ── Conversations ─────────────────────────────────────────────────────────────

CREATE TABLE conversations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    community_id     UUID NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
    author_id        UUID REFERENCES public.users(id) ON DELETE SET NULL,
    title            TEXT NOT NULL,
    body             TEXT NOT NULL,
    prompt_type      TEXT,
    is_deleted       BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at       TIMESTAMPTZ,
    deleted_by_moderator BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conversations_community_activity ON conversations (community_id, last_activity_at DESC);
CREATE INDEX idx_conversations_author_created ON conversations (author_id, created_at DESC);


-- ── Conversation Messages ─────────────────────────────────────────────────────

CREATE TABLE conversation_messages (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id      UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    author_id            UUID REFERENCES public.users(id) ON DELETE SET NULL,
    body                 TEXT NOT NULL,
    is_deleted           BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at           TIMESTAMPTZ,
    deleted_by_moderator BOOLEAN NOT NULL DEFAULT FALSE,
    toxicity_score       DOUBLE PRECISION,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conversation_messages_conversation_created ON conversation_messages (conversation_id, created_at ASC);
CREATE INDEX idx_conversation_messages_author_created ON conversation_messages (author_id, created_at DESC);


-- ── Message Replies ───────────────────────────────────────────────────────────

CREATE TABLE message_replies (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id           UUID NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    author_id            UUID REFERENCES public.users(id) ON DELETE SET NULL,
    body                 TEXT NOT NULL,
    is_deleted           BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at           TIMESTAMPTZ,
    deleted_by_moderator BOOLEAN NOT NULL DEFAULT FALSE,
    toxicity_score       DOUBLE PRECISION,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_message_replies_message_created ON message_replies (message_id, created_at ASC);
CREATE INDEX idx_message_replies_author_created ON message_replies (author_id, created_at DESC);


-- ── Conversation Hearts ───────────────────────────────────────────────────────

CREATE TABLE conversation_hearts (
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conversation_id, user_id)
);


-- ── Message Hearts ────────────────────────────────────────────────────────────

CREATE TABLE message_hearts (
    message_id UUID NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (message_id, user_id)
);


-- ── Reply Hearts ──────────────────────────────────────────────────────────────

CREATE TABLE reply_hearts (
    reply_id   UUID NOT NULL REFERENCES message_replies(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (reply_id, user_id)
);


-- ── Conversation Participants ─────────────────────────────────────────────────

CREATE TABLE conversation_participants (
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    first_joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conversation_id, user_id)
);

CREATE INDEX idx_conversation_participants_user ON conversation_participants (user_id);


-- ── Moderation: Filtered Messages (Audit Log) ─────────────────────────────────

CREATE TABLE moderation_filtered_messages (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_type TEXT NOT NULL CHECK (content_type IN ('conversation', 'message', 'reply')),
    content_id   UUID NOT NULL,
    author_id    UUID REFERENCES public.users(id) ON DELETE SET NULL,
    community_id UUID REFERENCES communities(id) ON DELETE SET NULL,
    original_text TEXT NOT NULL,
    layer        TEXT NOT NULL CHECK (layer IN ('profanity', 'hate_speech', 'report')),
    reason       TEXT,
    score        DOUBLE PRECISION,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_moderation_filtered_author_created ON moderation_filtered_messages (author_id, created_at DESC);
CREATE INDEX idx_moderation_filtered_content ON moderation_filtered_messages (content_type, content_id);


-- ── Moderation: Reports ───────────────────────────────────────────────────────

CREATE TABLE moderation_reports (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_type TEXT NOT NULL CHECK (content_type IN ('conversation', 'message', 'reply')),
    content_id   UUID NOT NULL,
    reporter_id  UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    reason       TEXT,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'reviewed', 'dismissed', 'actioned')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (content_type, content_id, reporter_id)
);

CREATE INDEX idx_moderation_reports_status_created ON moderation_reports (status, created_at DESC);
CREATE INDEX idx_moderation_reports_content ON moderation_reports (content_type, content_id);


-- ── Moderation: Bans ──────────────────────────────────────────────────────────

CREATE TABLE moderation_bans (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    reason     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_moderation_bans_user_expires ON moderation_bans (user_id, expires_at DESC);


-- ── Moderation: Notifications ─────────────────────────────────────────────────

CREATE TABLE moderation_notifications (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    type         TEXT NOT NULL CHECK (type IN ('content_removed', 'temporary_ban')),
    content_type TEXT CHECK (content_type IN ('conversation', 'message', 'reply')),
    content_id   UUID,
    layer        TEXT CHECK (layer IN ('profanity', 'hate_speech', 'report')),
    reason       TEXT,
    message      TEXT NOT NULL,
    is_read      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_moderation_notifications_user_unread ON moderation_notifications (user_id, is_read, created_at DESC);


-- ── User Reports ──────────────────────────────────────────────────────────────

CREATE TABLE user_reports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reported_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    reporter_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'reviewed', 'dismissed', 'actioned')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_user_reports_unique_pair ON user_reports (reported_id, reporter_id);
CREATE INDEX idx_user_reports_status_created ON user_reports (status, created_at DESC);
CREATE INDEX idx_user_reports_reported_created ON user_reports (reported_id, created_at DESC);
