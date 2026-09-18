-- Ensure timestamp updates are monotonically non-decreasing.
-- Protects against clock skew (NTP step corrections, VM migrations)
-- and concurrent requests where a slower transaction commits after a faster one.

-- 1. Chat updated_at trigger
CREATE OR REPLACE FUNCTION bump_chat_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE chats SET updated_at = GREATEST(updated_at, NOW()) WHERE id = NEW.chat_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
