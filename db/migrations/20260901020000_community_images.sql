-- Communities carry a photo of their own, the way users carry an avatar.
-- Only the URL lives here; the file itself sits in the `community-images`
-- Supabase storage bucket, keyed by community id.
--
-- Nullable because a community without a photo is a normal state, not a
-- half-finished one: the client falls back to a placeholder and the admin can
-- add a photo later from the community page.

ALTER TABLE communities
    ADD COLUMN image_url TEXT;

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
