-- Community activity notifications, stored as a digest rather than one row per post.
--
-- Every other notification type fans out one row per recipient at event time.
-- That cannot work here: a post in a 2000-member community would write 2000
-- rows, and a busy community would bury the notification centre in "someone
-- posted" entries. Instead each (member, community) pair gets at most ONE row,
-- updated in place -- its count climbs as posts arrive and resets when the
-- member next opens the community.

BEGIN;

-- Names the thing being digested, as 'community:<uuid>'. NULL for every
-- ordinary notification, which is why the unique index below is partial:
-- connection requests and chat adds must stay free to repeat.
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS group_key TEXT;

-- This index is not just a constraint, it is the mechanism: it gives
-- INSERT .. ON CONFLICT a target, so opening a digest and bumping an existing
-- one are the same single statement, at one round trip regardless of how many
-- members the community has.
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_user_group
ON notifications (user_id, group_key)
WHERE group_key IS NOT NULL;

COMMIT;
