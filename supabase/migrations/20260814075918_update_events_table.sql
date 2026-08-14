-- Update to events table migration
-- Change the foreign key constraint for the created_by column, and create a trigger to update the last_updated column

-- Events ───────────────────────────────────────────────────────────────────────────
create table public.events (
  id uuid not null default gen_random_uuid (),
  name character varying(100) not null,
  description character varying(1000) null,
  type text not null,
  starts_at timestamp with time zone not null,
  ends_at timestamp with time zone null,
  location character varying(500) not null,
  latitude double precision null,
  longitude double precision null,
  hosted_by_user_id uuid null,
  hosted_by_org_id uuid null,
  hosted_by_community_id uuid null,
  contact_email character varying(254) null,
  contact_phone character varying(20) null,
  price_cad numeric(10, 2) not null default 0.00,
  created_at timestamp with time zone null default now(),
  app_status public.application_status null default 'pending'::application_status,
  admin_notes jsonb null,
  created_by uuid not null default auth.uid (),
  last_updated timestamp with time zone not null default now(),
  constraint events_pkey primary key (id),
  constraint events_created_by_fkey foreign KEY (created_by) references auth.users (id),
  constraint events_hosted_by_community_id_fkey foreign KEY (hosted_by_community_id) references communities (id) on delete set null,
  constraint events_hosted_by_org_id_fkey foreign KEY (hosted_by_org_id) references organizations (id) on delete RESTRICT,
  constraint events_hosted_by_user_id_fkey foreign KEY (hosted_by_user_id) references users (id) on delete set null,
  constraint events_type_check check (
    (
      type = any (array['local'::text, 'virtual'::text])
    )
  )
) TABLESPACE pg_default;

-- Create update_last_updated function ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.update_last_updated()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.last_updated = NOW();
    RETURN NEW;
END;
$$;

-- Create events_last_updated trigger ───────────────────────────────────────────────────────────────────────────
CREATE TRIGGER events_last_updated
BEFORE UPDATE ON public.events
FOR EACH ROW
EXECUTE FUNCTION public.update_last_updated();