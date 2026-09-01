-- Community invites ride the existing DM chat as an ordinary message with a
-- community attached, rather than a parallel invite table. The recipient reads
-- it in the thread they already use, and an invite that is declined is simply a
-- message that was not acted on — there is no invite state to expire or clean up.

ALTER TABLE messages
    ADD COLUMN shared_community_id UUID REFERENCES communities(id) ON DELETE SET NULL;

-- Partial: only invite messages carry the column, and they are a small minority.
CREATE INDEX ON messages (shared_community_id) WHERE shared_community_id IS NOT NULL;
