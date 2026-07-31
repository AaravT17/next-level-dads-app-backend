-- Organizations & Messaging Migration
-- Creates the database schema for organization applications, representatives, chats, and messages.

-- Organizations ───────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS organizations (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    name                 VARCHAR(100) NOT NULL,
    email                VARCHAR(254) NOT NULL,
    phone                VARCHAR(20),
    city                 VARCHAR(100) NOT NULL,
    province             VARCHAR(2) NOT NULL,
    website              TEXT,
    description          VARCHAR(1000) NOT NULL,

    contact_name         VARCHAR(100) NOT NULL,
    contact_title        VARCHAR(100),
    contact_email        VARCHAR(254) NOT NULL,
    contact_phone        VARCHAR(20),

    status               TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),

    application_answers  JSONB NOT NULL DEFAULT '[]'::JSONB,
    notes                JSONB NOT NULL DEFAULT '[]'::JSONB,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at          TIMESTAMPTZ
);

-- Unique by email, case insensitive, to prevent duplicate organizations.
CREATE UNIQUE INDEX idx_organizations_email_unique
ON organizations (LOWER(email));

-- Organization Representatives ──────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS organization_representatives (
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    joined_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (organization_id, user_id)
);

-- Organization Chats ─────────────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS organization_chats (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id)
);

CREATE INDEX ON organization_chats (updated_at, id);

-- Organization Messages ───────────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS organization_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id         UUID NOT NULL REFERENCES organization_chats(id) ON DELETE CASCADE,
    sender_id       UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    reply_to_id     UUID REFERENCES organization_messages(id) ON DELETE SET NULL,
    content         TEXT NOT NULL,
    subject         JSONB,
    edited_at       TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON organization_messages (chat_id, created_at);
CREATE INDEX ON organization_messages (reply_to_id);

CREATE OR REPLACE FUNCTION bump_organization_chat_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE organization_chats SET updated_at = now() WHERE id = NEW.chat_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER bump_organization_chat_updated_at
AFTER INSERT ON organization_messages
FOR EACH ROW EXECUTE FUNCTION bump_organization_chat_updated_at();

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_representatives ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_messages ENABLE ROW LEVEL SECURITY;
