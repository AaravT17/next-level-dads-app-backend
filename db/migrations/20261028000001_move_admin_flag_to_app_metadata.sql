-- Move admin status from public.users.is_admin to auth.users app_metadata.role.
--
-- The role now lives in Supabase Auth, where only the service role can write it,
-- and the backend no longer reads users.is_admin. This copies each existing admin
-- across, then drops the column. Existing admins become ghosts: they browse
-- without a profile and can no longer take member actions.
--
-- The copy merges into app_metadata with ||, so provider and providers survive,
-- and a user who already has a role keeps it. It and the drop share one
-- transaction: if anything still depends on the column, the DROP fails and the
-- copy is undone with it. There is no CASCADE on purpose. The chat-level
-- chat_participants.is_admin is a different column and is not touched.
--
-- Apply AFTER the backend that no longer selects users.is_admin is deployed
-- (get_me read it, so dropping it first makes /users/me fail), and BEFORE
-- deleting any admin's profile, because this reads the flag from that row.
-- Run it once: a second run fails because the column is gone.

BEGIN;

UPDATE auth.users AS u
SET raw_app_meta_data = COALESCE(u.raw_app_meta_data, '{}'::jsonb) || '{"role": "admin"}'::jsonb
FROM public.users AS p
WHERE p.id = u.id
  AND p.is_admin
  AND u.raw_app_meta_data ->> 'role' IS NULL;

ALTER TABLE public.users DROP COLUMN is_admin;

COMMIT;
