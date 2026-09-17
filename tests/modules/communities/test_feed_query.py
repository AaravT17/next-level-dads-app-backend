"""What the home feed refuses to return.

`_build_feed_conversations_query` is pure, so its SQL can be read without a
database. That matters more here than for a query whose result is observable:
these are exclusions, and an exclusion that silently stops working looks exactly
like a quiet week in the feed. Nothing in a response says "and one reported
thread was left out".

The assertions match normalised SQL rather than exact formatting, so rewrapping
a clause does not fail the build.
"""

import re

import pytest

from app.common.config.constants import CONVERSATIONS_PAGE_LIMIT
from app.modules.communities.service import _build_feed_conversations_query
from uuid import uuid4

USER = uuid4()


def _sql(**kwargs) -> str:
    query, _ = _build_feed_conversations_query(USER, **kwargs)
    return re.sub(r'\s+', ' ', query).strip()


def _params(**kwargs) -> list:
    _, params = _build_feed_conversations_query(USER, **kwargs)
    return params


def test_threads_with_an_undecided_report_are_excluded():
    # The client renders these as a "potentially harmful content" placeholder.
    # In the feed there is nothing behind the placeholder to reveal, so the row
    # must not be fetched at all.
    assert (
        "NOT EXISTS ( SELECT 1 FROM moderation_reports mr "
        "WHERE mr.content_type = 'conversation' "
        "AND mr.content_id = c.id "
        "AND mr.status = 'pending' )"
    ) in _sql()


@pytest.mark.parametrize('following', [False, True])
def test_the_report_exclusion_applies_to_both_feed_scopes(following):
    # Following is a narrower feed, not a more permissive one.
    assert 'moderation_reports' in _sql(following=following)


def test_deleted_threads_are_excluded():
    assert 'WHERE NOT c.is_deleted' in _sql()


def test_moderator_filtered_threads_are_still_excluded():
    # The report exclusion is additive: the pre-existing automatic-layer filter
    # (profanity, hate speech) has to survive alongside it.
    assert 'moderation_filtered_messages' in _sql()


def test_placeholder_count_matches_parameter_count():
    # The builder hands asyncpg a splat, so the arity check in
    # tests/modules/moderation/test_sql_argument_counts.py cannot see this call.
    for kwargs in ({}, {'following': True}, {'cursor_id': uuid4(), 'cursor_created_at': 'now'}):
        query, params = _build_feed_conversations_query(USER, **kwargs)
        assert max(int(n) for n in re.findall(r'\$(\d+)', query)) == len(params)


def test_the_page_limit_is_the_last_bind_parameter():
    assert _params()[-1] == CONVERSATIONS_PAGE_LIMIT
