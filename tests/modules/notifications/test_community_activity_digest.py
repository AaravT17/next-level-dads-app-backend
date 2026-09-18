"""The community-activity digest.

Every other notification type fans out one row per recipient at event time.
This one cannot: a post in a large community would write a row per member, and
a busy community would bury the notification centre in "someone posted"
entries. So it is a digest -- one row per (member, community), updated in
place, cleared by a visit.

What can go wrong here is invisible from a response. A digest that notifies the
author, or that keeps counting after the member has already been and looked, or
that ignores the cooldown, all still return 200 and still show a plausible
badge. The statement is the only place those rules exist, so it is what is
asserted.

The SQL is a module constant, so this needs no database. Assertions match
normalised SQL rather than exact formatting, following test_new_activity_count.py,
so rewrapping a clause does not fail the build.
"""

import re

from app.common.config.constants import COMMUNITY_ACTIVITY_COOLDOWN_HOURS
from app.modules.notifications.service import UPSERT_COMMUNITY_ACTIVITY_DIGEST_SQL


def _norm(query: str) -> str:
    return re.sub(r'\s+', ' ', query).strip()


SQL = _norm(UPSERT_COMMUNITY_ACTIVITY_DIGEST_SQL)


def test_it_is_one_statement_not_a_row_per_member():
    # The whole design rests on this: opening a digest and adding to one are the
    # same INSERT, so the cost is one round trip whatever the member count. A
    # loop over members, or a bulk insert of one row each, is the thing this
    # replaced.
    assert SQL.count('INSERT INTO notifications') == 1
    assert 'ON CONFLICT (user_id, group_key)' in SQL
    assert 'FROM community_members cm' in SQL


def test_it_targets_the_partial_unique_index():
    # Ordinary notifications leave group_key NULL and must stay free to repeat,
    # so the index is partial and the conflict target has to say so. Without the
    # predicate Postgres cannot match the index and the statement fails outright.
    assert 'ON CONFLICT (user_id, group_key) WHERE group_key IS NOT NULL' in SQL


def test_the_author_is_never_notified_of_their_own_post():
    assert 'cm.user_id <> $2' in SQL


def test_clearing_the_notification_centre_also_restarts_the_count():
    # A digest row survives clear_all -- it is hidden by last_cleared_at, not
    # deleted -- so without last_cleared_at in the watermark a dismissed digest
    # comes back on the next post still carrying its old count, and one new
    # conversation reads as "8 new conversations".
    assert "COALESCE(uns.last_cleared_at, '-infinity'::timestamptz)" in SQL
    assert 'LEFT JOIN user_notification_state uns ON uns.user_id = cm.user_id' in SQL


def test_the_cooldown_keys_off_the_visit_not_the_clear():
    # Clearing the centre is not the same as catching up on a community, so it
    # must not buy six hours of silence from every community at once. The
    # cooldown reads _visited; only the count reset reads _since.
    assert "NOW() - (EXCLUDED.payload->>'_visited')::timestamptz >= make_interval(hours => $3)" in SQL
    assert "'_visited', COALESCE(cm.last_visited_at, cm.joined_at)" in SQL


def test_the_watermark_is_the_visit_falling_back_to_when_they_joined():
    # last_visited_at is NULL until the first visit and is never backfilled.
    # Without the COALESCE every comparison against it is NULL, so a member who
    # has never opened the community would never be notified about it -- exactly
    # the person the digest exists for.
    assert "COALESCE(cm.last_visited_at, cm.joined_at)" in SQL


def test_a_digest_raised_since_the_last_visit_is_added_to_rather_than_replaced():
    # Still unseen, so the count climbs instead of resetting to one.
    assert "notifications.created_at >= (EXCLUDED.payload->>'_since')::timestamptz" in SQL
    assert "jsonb_set( notifications.payload, '{count}'" in SQL


def test_a_digest_the_member_has_already_seen_starts_over_at_one():
    assert "WHEN notifications.created_at < (EXCLUDED.payload->>'_since')::timestamptz" in SQL
    assert 'THEN EXCLUDED.payload' in SQL


def test_a_visited_community_stays_silent_until_the_cooldown_has_run():
    # This is the only thing standing between a member and being notified again
    # the moment they close the community. If the DO UPDATE loses its WHERE,
    # every post re-raises a digest they just read.
    assert 'make_interval(hours => $3)' in SQL
    assert "NOW() - (EXCLUDED.payload->>'_visited')::timestamptz >= make_interval(hours => $3)" in SQL


def test_the_cooldown_is_hours_not_something_accidentally_enormous():
    # A typo turning six hours into six days silently stops the feature working
    # without failing anything.
    assert 0 < COMMUNITY_ACTIVITY_COOLDOWN_HOURS <= 24


def test_it_returns_the_count_so_only_a_freshly_opened_digest_pings_the_socket():
    # The caller publishes only where count = 1. Losing the count from RETURNING
    # would mean either a Redis publish per member on every post, or no socket
    # event at all.
    assert "RETURNING user_id, (payload->>'count')::int AS count" in SQL
