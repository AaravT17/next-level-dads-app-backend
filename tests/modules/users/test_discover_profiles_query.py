"""Who browse is allowed to return.

`_build_discover_profiles_query` is pure, so the admission rule can be read off
the SQL without a database. The rule is a single clause on the LEFT JOIN to
`connections`, and getting it wrong is invisible in a response: a dad you have
already requested looks like any other card until you notice the button.

The assertions match normalised SQL so that rewrapping a clause does not fail
the build.
"""

import re
from uuid import uuid4

import pytest

from app.common.config.constants import PROFILES_PAGE_LIMIT
from app.modules.users.service import _build_discover_profiles_query

USER = uuid4()


def _sql(**kwargs) -> str:
    query, _ = _build_discover_profiles_query(USER, **kwargs)
    return re.sub(r'\s+', ' ', query).strip()


def test_only_dads_with_no_connection_row_are_admitted():
    assert 'WHERE c.id IS NULL AND' in _sql()


def test_a_request_you_already_sent_no_longer_readmits_a_dad():
    # This clause used to sit beside `c.id IS NULL` and kept an already-requested
    # dad in the grid in a waiting state. Its absence is the whole change, and a
    # revert would restore it verbatim.
    assert "c.requesting_id = $1 AND c.status = 'pending'" not in _sql()


def test_the_caller_never_appears_in_their_own_browse_results():
    assert 'u.id != $1' in _sql()


@pytest.mark.parametrize(
    'kwargs',
    [
        {'name': 'Sam'},
        {'provinces': ['ON']},
        {'interests': ['hiking']},
        {'children_age_ranges': ['Toddler']},
        {'age_ranges': ['30-34']},
        {'cursor_id': uuid4(), 'cursor_created_at': 'now'},
    ],
)
def test_the_admission_rule_survives_every_filter(kwargs):
    # Filters are appended to the same WHERE clause, so a builder change that
    # dropped the leading rule would still produce valid SQL.
    assert 'c.id IS NULL AND' in _sql(**kwargs)


def test_placeholder_count_matches_parameter_count():
    query, params = _build_discover_profiles_query(
        USER,
        name='Sam',
        provinces=['ON'],
        age_ranges=['30-34'],
        interests=['hiking'],
        children_age_ranges=['Toddler'],
        cursor_id=uuid4(),
        cursor_created_at='now',
    )
    assert max(int(n) for n in re.findall(r'\$(\d+)', query)) == len(params)


def test_the_page_limit_is_the_last_bind_parameter():
    _, params = _build_discover_profiles_query(USER)
    assert params[-1] == PROFILES_PAGE_LIMIT
