"""Who may call each route, checked against the real app.

Routes are closed to accounts that browse without a profile (ghosts) unless they
deliberately use `get_viewer`. Two checks, both against the real app:

- Structure: read the dependency tree of every route, so a new route that forgets
  to choose an access dependency, or opens itself to ghosts by accident, fails here.
  What each dependency does is tested separately, in tests/common/dependencies.
- Smoke test (the end of this file): a handful of real requests, one route per access
  level, confirming that the dependency tree reflects what the running app does.
"""

from fastapi.routing import APIRoute

from app.common.dependencies.auth import (
    get_admin,
    get_consented_customer,
    get_current_access_token,
    get_current_user,
    get_customer,
    get_viewer,
)
from main import app

# Each set is named after the access dependency its routes use. The two without an
# explicit list are derived below: ADMIN_ROUTES (by path prefix) and
# CONSENTED_CUSTOMER_ROUTES (the default: every route not listed anywhere else).
#
# get_viewer: read-only routes a ghost may call. Every one of these returns data any
# member can already see; none of them is a private chat.
VIEWER_ROUTES = {
    ('GET', '/api/communities/'),
    ('GET', '/api/communities/{id}'),
    ('GET', '/api/communities/{id}/members'),
    ('GET', '/api/communities/{community_id}/conversations'),
    ('GET', '/api/conversations'),
    ('GET', '/api/conversations/{conversation_id}'),
    ('GET', '/api/conversations/{conversation_id}/messages'),
    ('GET', '/api/conversations/{conversation_id}/participants'),
    ('GET', '/api/messages/{message_id}/replies'),
    ('GET', '/api/events/'),
    ('GET', '/api/events/{id}'),
    ('GET', '/api/users/{id}'),
    ('GET', '/api/users/'),
}

# get_customer: a non-ghost is required, but consent cannot be. Creating a profile and
# accepting the legal documents both come before anyone has accepted anything, and
# /me is how the frontend learns whether there is a profile and what has been accepted.
CUSTOMER_ROUTES = {
    ('POST', '/api/users/'),
    ('GET', '/api/users/me'),
    ('POST', '/api/users/me/legal-acceptances'),
}

# get_current_user only: open to any signed-in account, whatever its role or consent
# state. Interests feed the profile-setup form, which comes before any consent exists.
CURRENT_USER_ROUTES = {('GET', '/api/interests/')}

# No user dependency: anyone may call these. They sign someone in, or work from a
# token or cookie directly.
PUBLIC_ROUTES = {
    ('POST', '/api/auth/register'),
    ('POST', '/api/auth/login'),
    ('POST', '/api/auth/oauth/session'),
    ('POST', '/api/auth/refresh'),
    ('POST', '/api/auth/logout'),
}


def _dependencies(dependant):
    for sub in dependant.dependencies:
        yield sub.call
        yield from _dependencies(sub)


def _routes() -> dict[tuple[str, str], list]:
    routes = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        calls = list(_dependencies(route.dependant))
        for method in route.methods:
            routes[(method, route.path)] = calls
    return routes


def _uses(calls, dependency) -> bool:
    return any(call is dependency for call in calls)


# get_admin: everything under the admin prefix.
ADMIN_ROUTES = {key for key in _routes() if key[1].startswith('/api/admin/')}

# get_consented_customer: the default. Every route not named in another set.
CONSENTED_CUSTOMER_ROUTES = (
    set(_routes()) - VIEWER_ROUTES - CUSTOMER_ROUTES - CURRENT_USER_ROUTES - PUBLIC_ROUTES - ADMIN_ROUTES
)


def test_exactly_the_intended_routes_are_open_to_ghosts():
    viewer = {key for key, calls in _routes().items() if _uses(calls, get_viewer)}

    assert viewer == VIEWER_ROUTES


def test_the_customer_only_routes_are_exactly_the_expected_ones():
    customer = {
        key
        for key, calls in _routes().items()
        if _uses(calls, get_customer) and not _uses(calls, get_consented_customer)
    }

    assert customer == CUSTOMER_ROUTES


def test_the_current_user_only_routes_are_exactly_the_expected_ones():
    current_user_only = {
        key
        for key, calls in _routes().items()
        if _uses(calls, get_current_user)
        and not any(_uses(calls, dep) for dep in (get_customer, get_consented_customer, get_viewer, get_admin))
    }

    assert current_user_only == CURRENT_USER_ROUTES


def test_the_public_routes_are_exactly_the_routes_without_a_user_dependency():
    public = {key for key, calls in _routes().items() if not _uses(calls, get_current_user)}

    assert public == PUBLIC_ROUTES


def test_the_consented_customer_routes_are_exactly_the_rest():
    # The default: a route not named in any other set must be consented-customer. One
    # that uses no access dependency, or a looser one, shows up as a missing route here.
    consented = {key for key, calls in _routes().items() if _uses(calls, get_consented_customer)}

    assert CONSENTED_CUSTOMER_ROUTES, 'expected member routes to exist'
    assert consented == CONSENTED_CUSTOMER_ROUTES


def test_the_admin_routes_are_exactly_the_ones_under_the_admin_prefix():
    admin = {key for key, calls in _routes().items() if _uses(calls, get_admin)}

    assert ADMIN_ROUTES, 'expected admin routes to exist'
    assert admin == ADMIN_ROUTES


def test_the_logout_route_still_reads_the_bearer_token():
    # Logout carries no user dependency (PUBLIC_ROUTES) but must not be anonymous.
    calls = _routes()[('POST', '/api/auth/logout')]

    assert _uses(calls, get_current_access_token)


# --- Smoke test: the dependency tree matches what happens over HTTP ---------------
#
# Which dependency each route declares is checked above, and what each dependency
# does is checked in tests/common/dependencies. These few requests, one real route
# per access level, confirm that reading the dependency tree reflects what the
# running app does, which is what lets the other two checks be trusted.
#
# The database and the Supabase client are stand-ins. A 401 or 403 therefore means
# an access dependency refused the caller; anything else (a 422 for a missing body,
# a 500 because the connection is a stand-in) means the request got past
# authentication and into the handler.

import re  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.common.dependencies.auth as auth  # noqa: E402
from app.common.dependencies.db import get_db, get_pool  # noqa: E402

REFUSED = (401, 403)
SOME_ID = '00000000-0000-0000-0000-000000000001'

_CALLERS = {
    'anonymous': {'token': False},
    'unrecognized role': {'role': 'superuser'},
    'admin': {'role': 'admin'},
    'member': {},
    'unconsented member': {'consented': False},
}

# (caller, route, expected status). None means "gets past authentication".
_SMOKE = [
    ('anonymous', ('GET', '/api/chats/'), 401),
    ('unrecognized role', ('GET', '/api/events/'), 403),
    ('admin', ('POST', '/api/chats/'), 403),  # get_consented_customer
    ('admin', ('POST', '/api/users/'), 403),  # get_customer
    ('admin', ('GET', '/api/events/'), None),  # get_viewer
    ('admin', ('GET', '/api/interests/'), None),  # get_current_user
    ('admin', ('GET', '/api/admin/bans'), None),  # get_admin
    ('member', ('GET', '/api/admin/bans'), 403),
    ('unconsented member', ('GET', '/api/chats/'), 403),
    ('unconsented member', ('GET', '/api/events/'), 403),
    ('unconsented member', ('GET', '/api/users/me'), None),  # get_customer, no consent needed
    ('member', ('GET', '/api/chats/'), None),
]


@pytest.fixture(autouse=True)
def _stand_in_infrastructure():
    async def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_pool] = lambda: object()
    yield
    app.dependency_overrides.clear()


def _call(monkeypatch, key, *, role=None, consented=True, token=True) -> int:
    method, path = key
    metadata = {'role': role} if role is not None else {}

    async def get_user(_token):
        return SimpleNamespace(user=SimpleNamespace(id='u1', app_metadata=metadata))

    async def check_consent(_conn, _user_id):
        return consented

    monkeypatch.setattr(auth, 'get_supabase', lambda: SimpleNamespace(auth=SimpleNamespace(get_user=get_user)))
    monkeypatch.setattr(auth, 'check_consent', check_consent)

    url = re.sub(r'\{[^}]+\}', SOME_ID, path)
    headers = {'Authorization': 'Bearer token'} if token else {}
    client = TestClient(app, raise_server_exceptions=False)
    return client.request(method, url, headers=headers).status_code


@pytest.mark.parametrize(
    ('caller', 'key', 'expected'),
    _SMOKE,
    ids=[f'{caller} -> {method} {path}' for caller, (method, path), _ in _SMOKE],
)
def test_real_requests_get_the_access_the_dependency_tree_says(monkeypatch, caller, key, expected):
    status = _call(monkeypatch, key, **_CALLERS[caller])

    if expected is None:
        assert status not in REFUSED
    else:
        assert status == expected
