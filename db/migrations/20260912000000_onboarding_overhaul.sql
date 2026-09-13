-- Onboarding overhaul: curated interests with slugs, new profile fields, updated view.

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════
-- 1. INTERESTS: add slug column, merge/remap, delete deprecated, seed new
-- ══════════════════════════════════════════════════════════════════════════════

-- 1a. Add nullable slug column
ALTER TABLE interests ADD COLUMN slug TEXT;


-- 1b. Merge interests that map many-to-one (prod data migration)
--
--     Each group names a target and the source rows folded into it. The target
--     is created first, then every user holding a source interest is moved onto
--     it, then the sources are dropped.
--
--     Creating the target first is what makes this safe across databases that
--     hold different subsets of these names. The earlier form renamed one
--     nominated source into the target and then read the target back with a
--     scalar subquery -- which returned NULL, not "no rows", on any database
--     where that particular source was absent but another source was present,
--     and NULL fails user_interests.interest_id NOT NULL. Our two production
--     databases differ in exactly that way: one has 'Food' and never had
--     'Cooking'.
--
--     The target may end up with a fresh id rather than inheriting a source's.
--     Nothing depends on that: user_interests is the only table referencing
--     interests(id), and every row of it is remapped here.

DO $$
DECLARE
    grp RECORD;
BEGIN
    FOR grp IN
        SELECT * FROM (VALUES
            ('Food & Cooking',       'food',               ARRAY['Cooking', 'Food']),
            ('DIY & Home Projects',  'diy',                ARRAY['Diy', 'Home Projects']),
            ('Movies & TV',          'movies-tv',          ARRAY['Movies']),
            ('Health & Wellness',    'health-wellness',    ARRAY['Mental Wellness']),
            ('Faith & Spirituality', 'faith-spirituality', ARRAY['Faith']),
            ('Sports',               'sports',             ARRAY['Soccer']),
            ('Fitness',              'fitness',            ARRAY['Running', 'Martial Arts'])
        ) AS t(target_name, target_slug, source_names)
    LOOP
        INSERT INTO interests (name, slug)
        VALUES (grp.target_name, grp.target_slug)
        ON CONFLICT (name) DO UPDATE SET slug = EXCLUDED.slug;

        INSERT INTO user_interests (user_id, interest_id)
        SELECT ui.user_id, target.id
        FROM user_interests ui
        JOIN interests src    ON src.id = ui.interest_id
        JOIN interests target ON target.name = grp.target_name
        WHERE src.name = ANY (grp.source_names)
        ON CONFLICT DO NOTHING;

        DELETE FROM interests WHERE name = ANY (grp.source_names);
    END LOOP;
END
$$;


-- 1c. Upsert the full curated set of 30 interests
--     Existing rows get their slug set/corrected, missing rows get inserted.
--
--     This runs BEFORE the delete below, and the order is load-bearing. Step 1b
--     only assigns slugs to the seven merge targets, so a curated-but-unmerged
--     interest -- Gaming, Golf, Travel, and twenty more -- still has a NULL slug
--     at this point. Deleting first would cascade every user's link to all of
--     them away and then re-seed the names as empty rows, quietly stripping most
--     users of most of their interests. Setting the slugs first means the delete
--     that follows only reaches genuinely non-curated names.
INSERT INTO interests (name, slug) VALUES
    ('Sports',               'sports'),
    ('Fitness',              'fitness'),
    ('Golf',                 'golf'),
    ('Outdoors',             'outdoors'),
    ('Gaming',               'gaming'),
    ('Food & Cooking',       'food'),
    ('Music',                'music'),
    ('Movies & TV',          'movies-tv'),
    ('Comedy & Standup',     'comedy'),
    ('Theatre',              'theatre'),
    ('True Crime',           'true-crime'),
    ('Travel',               'travel'),
    ('Tech',                 'tech'),
    ('Cars',                 'cars'),
    ('Reading',              'reading'),
    ('Photography',          'photography'),
    ('Podcasts',             'podcasts'),
    ('Art',                  'art'),
    ('Fashion',              'fashion'),
    ('Collectibles',         'collectibles'),
    ('History',              'history'),
    ('DIY & Home Projects',  'diy'),
    ('Board Games',          'board-games'),
    ('Pets',                 'pets'),
    ('Gardening',            'gardening'),
    ('Volunteering',         'volunteering'),
    ('Finance',              'finance'),
    ('Entrepreneurship',     'entrepreneurship'),
    ('Faith & Spirituality', 'faith-spirituality'),
    ('Health & Wellness',    'health-wellness')
ON CONFLICT (name) DO UPDATE SET slug = EXCLUDED.slug;


-- 1d. Delete all non-curated interests (cascade removes user_interests rows)
--     Everything curated now carries a slug, so what is left with a NULL slug is
--     genuinely deprecated (Parenting, Wine, Coffee, Writing, ...) or a custom
--     user-created interest. Those users do lose the selection -- that is the
--     intent of curating the list.
DELETE FROM interests WHERE slug IS NULL;


-- 1e. Add NOT NULL and UNIQUE constraints on slug
ALTER TABLE interests ALTER COLUMN slug SET NOT NULL;
ALTER TABLE interests ADD CONSTRAINT interests_slug_unique UNIQUE (slug);


-- ══════════════════════════════════════════════════════════════════════════════
-- 2. REMOVE QUEBEC USERS (legal requirement — cannot operate in QC)
-- ══════════════════════════════════════════════════════════════════════════════

DELETE FROM auth.users
WHERE id IN (SELECT id FROM users WHERE province = 'QC');


-- ══════════════════════════════════════════════════════════════════════════════
-- 3. USERS: add new onboarding fields
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE users
    ADD COLUMN kid_count         INTEGER,
    ADD COLUMN goals             TEXT[],
    ADD COLUMN primary_goal      TEXT,
    ADD COLUMN connection_styles TEXT[],
    ADD COLUMN match_priorities  TEXT[],
    ADD COLUMN icebreakers       JSONB;


-- ══════════════════════════════════════════════════════════════════════════════
-- 4. VIEW: recreate user_profiles with new fields and interest slugs
-- ══════════════════════════════════════════════════════════════════════════════

DROP VIEW IF EXISTS public.user_profiles;

CREATE VIEW public.user_profiles WITH (security_invoker = on) AS
SELECT
    u.id,
    u.name,
    COALESCE(DATE_PART('year', AGE(u.date_of_birth))::int, u.age) AS age,
    u.date_of_birth,
    u.city,
    u.province,
    u.about,
    u.avatar_url,
    u.kid_count,
    u.goals,
    u.primary_goal,
    u.connection_styles,
    u.match_priorities,
    u.icebreakers,
    u.created_at,
    COALESCE(
        (SELECT array_agg(jsonb_build_object('id', i.id, 'slug', i.slug))
         FROM public.user_interests ui
         JOIN public.interests i ON i.id = ui.interest_id
         WHERE ui.user_id = u.id),
        '{}'
    ) AS interests,
    COALESCE(
        (SELECT array_agg(uc.age_range)
         FROM public.user_children uc
         WHERE uc.user_id = u.id),
        '{}'
    ) AS children_age_ranges
FROM public.users u;

COMMIT;
