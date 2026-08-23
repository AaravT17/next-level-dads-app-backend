-- User preferences and legal document acceptances.

-- ── User Preferences ──────────────────────────────────────────────────────────

CREATE TABLE user_preferences (
    user_id                 UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    marketing_emails_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Backfill existing users with default preferences
INSERT INTO user_preferences (user_id)
SELECT id FROM users
ON CONFLICT DO NOTHING;


-- ── User Legal Acceptances ────────────────────────────────────────────────────

CREATE TABLE user_legal_acceptances (
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL CHECK (document_type IN ('terms', 'privacy_policy', 'community_guidelines')),
    accepted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, document_type)
);
