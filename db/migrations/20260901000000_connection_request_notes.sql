-- Optional note attached to a connection request.

-- A short message the sender writes when asking to connect, shown to the
-- recipient on the request card so they can decide without opening a chat.
-- Chats require an accepted connection (see chats service), so a pending
-- request has nowhere else to carry this text.
ALTER TABLE connections
    ADD COLUMN note TEXT;

ALTER TABLE connections
    ADD CONSTRAINT connection_note_length CHECK (
        note IS NULL OR char_length(note) <= 300
    );
