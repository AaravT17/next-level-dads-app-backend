-- Who performed a moderator action.
--
-- Every admin route resolves the acting admin through get_admin_user and then
-- discards it: content removals, bans and ban lifts all land with no record of
-- who did them. For sanctions the user can see -- a week-long ban, a deleted
-- post -- "which moderator actioned this, and when" needs an answer after the
-- fact, and today there is nowhere to look.
--
-- Every column is nullable. The automatic layers act with no admin behind them,
-- and rows written before this migration have no one to attribute.

ALTER TABLE moderation_reports
    ADD COLUMN actioned_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN actioned_at TIMESTAMPTZ;

ALTER TABLE user_reports
    ADD COLUMN actioned_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN actioned_at TIMESTAMPTZ;

-- A ban has two distinct moderator actions with different actors: issuing it,
-- and lifting it early. `expires_at` moving to the past is the lift itself, so
-- only the actor needs recording.
ALTER TABLE moderation_bans
    ADD COLUMN created_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN lifted_by  UUID REFERENCES public.users(id) ON DELETE SET NULL;

-- NULL here means an automatic layer removed the content; a value means a
-- moderator actioned a report.
ALTER TABLE moderation_filtered_messages
    ADD COLUMN actioned_by UUID REFERENCES public.users(id) ON DELETE SET NULL;
