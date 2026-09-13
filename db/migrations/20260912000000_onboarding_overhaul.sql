-- Onboarding overhaul: curated interests with slugs, new profile fields, updated view.

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════
-- 1. INTERESTS: add slug column, merge/remap, delete deprecated, seed new
-- ══════════════════════════════════════════════════════════════════════════════

-- 1a. Add nullable slug column
ALTER TABLE interests ADD COLUMN slug TEXT;


-- 1b. Merge interests that map many-to-one (prod data migration)
--     Pattern: rename survivor, set slug, remap users from doomed row, delete doomed row.
--     These are no-ops on a fresh DB (WHERE clauses match nothing).

-- Food + Cooking → food
UPDATE interests SET name = 'Food & Cooking', slug = 'food' WHERE name = 'Cooking';
INSERT INTO user_interests (user_id, interest_id)
SELECT ui.user_id, (SELECT id FROM interests WHERE name = 'Food & Cooking')
FROM user_interests ui
JOIN interests i ON i.id = ui.interest_id
WHERE i.name = 'Food'
ON CONFLICT DO NOTHING;
DELETE FROM interests WHERE name = 'Food';

-- DIY + Home Projects → diy
UPDATE interests SET name = 'DIY & Home Projects', slug = 'diy' WHERE name = 'Diy';
INSERT INTO user_interests (user_id, interest_id)
SELECT ui.user_id, (SELECT id FROM interests WHERE name = 'DIY & Home Projects')
FROM user_interests ui
JOIN interests i ON i.id = ui.interest_id
WHERE i.name = 'Home Projects'
ON CONFLICT DO NOTHING;
DELETE FROM interests WHERE name = 'Home Projects';

-- Movies → Movies & TV
UPDATE interests SET name = 'Movies & TV', slug = 'movies-tv' WHERE name = 'Movies';

-- Mental Wellness → Health & Wellness
UPDATE interests SET name = 'Health & Wellness', slug = 'health-wellness' WHERE name = 'Mental Wellness';

-- Faith → Faith & Spirituality
UPDATE interests SET name = 'Faith & Spirituality', slug = 'faith-spirituality' WHERE name = 'Faith';

-- Soccer → merge into Sports
UPDATE interests SET slug = 'sports' WHERE name = 'Sports';
INSERT INTO user_interests (user_id, interest_id)
SELECT ui.user_id, (SELECT id FROM interests WHERE name = 'Sports')
FROM user_interests ui
JOIN interests i ON i.id = ui.interest_id
WHERE i.name = 'Soccer'
ON CONFLICT DO NOTHING;
DELETE FROM interests WHERE name = 'Soccer';

-- Running, Martial Arts → merge into Fitness
UPDATE interests SET slug = 'fitness' WHERE name = 'Fitness';
INSERT INTO user_interests (user_id, interest_id)
SELECT ui.user_id, (SELECT id FROM interests WHERE name = 'Fitness')
FROM user_interests ui
JOIN interests i ON i.id = ui.interest_id
WHERE i.name IN ('Running', 'Martial Arts')
ON CONFLICT DO NOTHING;
DELETE FROM interests WHERE name IN ('Running', 'Martial Arts');


-- 1c. Delete all non-curated interests (cascade removes user_interests rows)
--     This catches deprecated interests (Parenting, Wine, Coffee, Writing, etc.)
--     and any custom user-created interests.
DELETE FROM interests WHERE slug IS NULL;


-- 1d. Upsert the full curated set of 30 interests
--     Existing rows get their slug set/corrected, missing rows get inserted.
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
