-- Phase 2 platform work: connection request notes, community invite messages,
-- community images, and the moderation audit trail.
--
-- Consolidated from four migrations that were previously separate
-- (20260901000000, 20260901010000, 20260901020000, 20260909000000). There is no
-- migration runner in this repo, so there is no ledger to contradict: applying
-- this once is equivalent to having applied those four in order.
--
-- Every step is idempotent. Re-running is a no-op, which is what makes this
-- safe to point at a database that already has some of these changes -- the two
-- production databases are not in the same state.
--
-- Ordering: this must run BEFORE 20260912000000_onboarding_overhaul.sql, which
-- drops and recreates the user_profiles view. Nothing here touches that view,
-- but the timestamps encode the intended order and should be respected.

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════
-- 1. CONNECTIONS: optional note on a connection request
-- ══════════════════════════════════════════════════════════════════════════════

-- A short message the sender writes when asking to connect, shown to the
-- recipient on the request card so they can decide without opening a chat.
-- Chats require an accepted connection (see chats service), so a pending
-- request has nowhere else to carry this text.
ALTER TABLE connections
    ADD COLUMN IF NOT EXISTS note TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'connection_note_length'
          AND conrelid = 'public.connections'::regclass
    ) THEN
        ALTER TABLE connections
            ADD CONSTRAINT connection_note_length CHECK (
                note IS NULL OR char_length(note) <= 300
            );
    END IF;
END
$$;


-- ══════════════════════════════════════════════════════════════════════════════
-- 2. MESSAGES: community invites ride the existing DM thread
-- ══════════════════════════════════════════════════════════════════════════════

-- Community invites ride the existing DM chat as an ordinary message with a
-- community attached, rather than a parallel invite table. The recipient reads
-- it in the thread they already use, and an invite that is declined is simply a
-- message that was not acted on — there is no invite state to expire or clean up.
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS shared_community_id UUID
        REFERENCES communities(id) ON DELETE SET NULL;

-- Partial: only invite messages carry the column, and they are a small minority.
-- Named explicitly (the original let Postgres generate one) so IF NOT EXISTS has
-- something to match on a re-run.
CREATE INDEX IF NOT EXISTS messages_shared_community_id_idx
    ON messages (shared_community_id)
    WHERE shared_community_id IS NOT NULL;


-- ══════════════════════════════════════════════════════════════════════════════
-- 3. COMMUNITIES: a photo of their own
-- ══════════════════════════════════════════════════════════════════════════════

-- Communities carry a photo of their own, the way users carry an avatar.
-- Only the URL lives here; the file itself sits in the `community-images`
-- Supabase storage bucket, keyed by community id.
--
-- Nullable because a community without a photo is a normal state, not a
-- half-finished one: the client falls back to a placeholder and the admin can
-- add a photo later from the community page.
ALTER TABLE communities
    ADD COLUMN IF NOT EXISTS image_url TEXT;

-- The bucket the URLs point at. Public-read so the <img> in a community card
-- needs no signed URL; writes stay closed to anon/authenticated because every
-- upload goes through the backend's service-role client after an admin check.
INSERT INTO storage.buckets (id, name, public)
VALUES ('community-images', 'community-images', TRUE)
ON CONFLICT (id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'storage'
          AND tablename = 'objects'
          AND policyname = 'Community images are publicly readable'
    ) THEN
        CREATE POLICY "Community images are publicly readable"
            ON storage.objects FOR SELECT
            USING (bucket_id = 'community-images');
    END IF;
END
$$;


-- ══════════════════════════════════════════════════════════════════════════════
-- 4. MODERATION: who performed a moderator action
-- ══════════════════════════════════════════════════════════════════════════════

-- Every admin route resolves the acting admin through get_admin_user and then
-- discards it: content removals, bans and ban lifts all land with no record of
-- who did them. For sanctions the user can see -- a week-long ban, a deleted
-- post -- "which moderator actioned this, and when" needs an answer after the
-- fact, and today there is nowhere to look.
--
-- Every column is nullable. The automatic layers act with no admin behind them,
-- and rows written before this migration have no one to attribute.
--
-- This must be applied together with the backend code that writes actioned_by,
-- actioned_at, created_by and lifted_by.
ALTER TABLE moderation_reports
    ADD COLUMN IF NOT EXISTS actioned_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS actioned_at TIMESTAMPTZ;

ALTER TABLE user_reports
    ADD COLUMN IF NOT EXISTS actioned_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS actioned_at TIMESTAMPTZ;

-- A ban has two distinct moderator actions with different actors: issuing it,
-- and lifting it early. `expires_at` moving to the past is the lift itself, so
-- only the actor needs recording.
ALTER TABLE moderation_bans
    ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS lifted_by  UUID REFERENCES public.users(id) ON DELETE SET NULL;

-- NULL here means an automatic layer removed the content; a value means a
-- moderator actioned a report.
ALTER TABLE moderation_filtered_messages
    ADD COLUMN IF NOT EXISTS actioned_by UUID REFERENCES public.users(id) ON DELETE SET NULL;

COMMIT;
