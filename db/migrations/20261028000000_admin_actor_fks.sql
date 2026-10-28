-- Point the "who did this" columns of the moderation tables at auth.users.
--
-- Admins sign in without a profile: they have a row in auth.users but none in
-- public.users. These five columns record the admin behind a ban, a lift, a
-- report decision or a content removal, and they referenced public.users, so
-- every one of those actions would fail with a foreign key violation.
--
-- auth.users is also what keeps the history: deleting a profile row no longer
-- blanks who made a decision. ON DELETE SET NULL is kept, so deleting the auth
-- account itself still clears the reference instead of failing.
--
-- Apply this BEFORE deleting any admin's public.users row. Under the old
-- constraints that delete sets these columns to NULL and loses the attribution.
--
-- The constraints keep their names; only the table they reference changes. DROP
-- CONSTRAINT has no IF EXISTS on purpose: a wrong name should abort the whole
-- transaction rather than leave the old constraint in place beside the new one.

BEGIN;

ALTER TABLE moderation_filtered_messages
    DROP CONSTRAINT moderation_filtered_messages_actioned_by_fkey,
    ADD CONSTRAINT moderation_filtered_messages_actioned_by_fkey
        FOREIGN KEY (actioned_by) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE moderation_reports
    DROP CONSTRAINT moderation_reports_actioned_by_fkey,
    ADD CONSTRAINT moderation_reports_actioned_by_fkey
        FOREIGN KEY (actioned_by) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE user_reports
    DROP CONSTRAINT user_reports_actioned_by_fkey,
    ADD CONSTRAINT user_reports_actioned_by_fkey
        FOREIGN KEY (actioned_by) REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE moderation_bans
    DROP CONSTRAINT moderation_bans_created_by_fkey,
    DROP CONSTRAINT moderation_bans_lifted_by_fkey,
    ADD CONSTRAINT moderation_bans_created_by_fkey
        FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL,
    ADD CONSTRAINT moderation_bans_lifted_by_fkey
        FOREIGN KEY (lifted_by) REFERENCES auth.users(id) ON DELETE SET NULL;

COMMIT;
