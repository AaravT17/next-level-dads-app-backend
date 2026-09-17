"""The "N active since you last visited" count on a community card.

The count exists to pull people back into communities that moved while they were
away, so the ways it can quietly go wrong are all ways it stops pulling: counting
from the wrong moment, counting content nobody can see, or costing enough that it
gets taken out again. None of those are visible in a response -- a badge that
says nothing looks exactly like a quiet week.

The query builders are pure, so this needs no database. Assertions match
normalised SQL rather than exact formatting, following test_feed_query.py, so
rewrapping a clause does not fail the build.
"""

import re
from uuid import uuid4

from app.modules.communities.service import (
    NEW_ACTIVITY_CAP,
    _build_discover_communities_query,
    _build_get_community_query,
    _build_get_user_communities_query,
)

USER = uuid4()
COMMUNITY = uuid4()


def _norm(query: str) -> str:
    return re.sub(r'\s+', ' ', query).strip()


def _mine(**kwargs) -> str:
    query, _ = _build_get_user_communities_query(USER, **kwargs)
    return _norm(query)


def test_the_count_measures_from_your_last_visit():
    assert 'conv.last_activity_at > COALESCE(cm.last_visited_at, cm.joined_at)' in _mine()


def test_a_member_who_has_never_visited_counts_from_when_they_joined():
    # last_visited_at is NULL until the first visit and is never backfilled.
    # Without the COALESCE the comparison is NULL, the count is 0, and the badge
    # never appears for exactly the people it is meant to bring back.
    assert 'COALESCE(cm.last_visited_at, cm.joined_at)' in _mine()


def test_the_count_is_scoped_to_the_community_on_the_card():
    assert 'conv.community_id = c.id' in _mine()


def test_deleted_conversations_are_not_counted():
    assert 'NOT conv.is_deleted' in _mine()


def test_moderator_removed_conversations_are_not_counted():
    # The card must not promise more threads than the community page will render.
    sql = _mine()
    assert "mfm.content_type = 'conversation' AND mfm.content_id = conv.id" in sql
    assert "mfm.layer = 'report'" in sql


def test_the_count_is_capped():
    # The whole cost argument for this feature rests on the LIMIT: without it a
    # busy community turns every card render into an unbounded scan.
    assert f'LIMIT {NEW_ACTIVITY_CAP} ) t' in _mine()


def test_the_cap_stays_within_what_the_badge_can_show():
    # NavBadge renders 99+ past two digits, so counting further buys nothing.
    assert NEW_ACTIVITY_CAP >= 100


def test_the_count_reads_the_callers_own_membership_row():
    # cm is the caller's row via `WHERE cm.user_id = $1`. If the member_count
    # subquery reused that alias it would shadow it, and the watermark would come
    # from an arbitrary member instead.
    sql = _mine()
    assert 'JOIN community_members cm ON c.id = cm.community_id' in sql
    assert 'WHERE cm.user_id = $1' in sql
    assert 'FROM community_members cm WHERE' not in sql


def test_the_count_does_not_disturb_the_existing_member_count():
    assert 'FROM community_members m WHERE m.community_id = c.id) AS member_count' in _mine()


def test_the_count_survives_the_search_and_cursor_branches():
    # Both add conditions to the same WHERE, so a broken interpolation would
    # only show up on a filtered or paginated page.
    filtered = _mine(name='toddler')
    paged = _mine(cursor_id=COMMUNITY, cursor_created_at='2026-01-01')

    assert 'new_activity_count' in filtered
    assert 'new_activity_count' in paged


def test_search_and_cursor_still_pass_the_same_parameters():
    # The count is inlined SQL, not a parameter -- it must not shift $n numbering.
    _, plain = _build_get_user_communities_query(USER)
    _, filtered = _build_get_user_communities_query(USER, name='toddler')

    assert len(plain) == 2
    assert len(filtered) == 3


def test_discover_reports_no_new_activity():
    # Discover only lists communities you are not in, so there is no watermark
    # and nothing to return to. It must still return the field: CommunityResponse
    # is shared across every read path.
    query, _ = _build_discover_communities_query(USER)

    assert '0 AS new_activity_count' in _norm(query)
    assert 'last_visited_at' not in _norm(query)


def test_the_community_page_itself_reports_no_new_activity():
    # Opening the community is what clears the badge; the page it clears on has
    # no use for the number.
    query, _ = _build_get_community_query(COMMUNITY, USER)

    assert '0 AS new_activity_count' in _norm(query)
