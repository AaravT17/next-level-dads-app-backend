-- Community visit tracking: "N conversations active since you last visited".
--
-- The watermark lives on community_members because a row already exists there for
-- every (community, user) pair -- no new table, and the per-card count becomes a
-- correlated subquery on a join the read query already performs.
--
-- Existing rows stay NULL rather than being backfilled. Reads use
-- COALESCE(last_visited_at, joined_at), so a member who has never been stamped sees
-- what is new since they joined rather than the community's entire history.

ALTER TABLE community_members ADD COLUMN IF NOT EXISTS last_visited_at TIMESTAMPTZ;

-- get_user_communities and the new user-stats aggregate both filter on user_id
-- alone, which the composite PK (community_id, user_id) cannot serve -- its leading
-- column is community_id, and Postgres has no skip scan.
CREATE INDEX IF NOT EXISTS idx_community_members_user ON community_members (user_id);
