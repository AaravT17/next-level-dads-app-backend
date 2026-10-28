"""Unit tests for resolving the caller's identity and role, and for the access
dependencies built on top of it.

`get_current_user` is the single place a token becomes an id and a role, and the
role it reports decides what a caller may do, so the cases that matter are the
ones where the token or its metadata is malformed. The access dependencies
(`get_customer`, `get_consented_customer`, `get_viewer`, `get_admin`) are then
checked against every role. Supabase and the consent lookup are replaced with
fakes; nothing here connects to anything.
"""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

import app.common.dependencies.auth as auth
from app.common.dependencies.auth import (
    CurrentUser,
    get_admin,
    get_consented_customer,
    get_current_user,
    get_customer,
    get_viewer,
)
from app.common.dependencies.db import get_db

BEARER = {'Authorization': 'Bearer token'}


class _FakeAuth:
    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def get_user(self, token: str):
        if self._error:
            raise self._error
        return self._result


def _supabase_returning(user_id='user-1', app_metadata=None):
    result = SimpleNamespace(user=SimpleNamespace(id=user_id, app_metadata=app_metadata))
    return SimpleNamespace(auth=_FakeAuth(result=result))


def _consent(monkeypatch, accepted: bool) -> list[str]:
    """Replace the consent lookup, returning the user ids it was asked about."""
    asked: list[str] = []

    async def check_consent(_conn, user_id):
        asked.append(user_id)
        return accepted

    monkeypatch.setattr(auth, 'check_consent', check_consent)
    return asked


def _client(monkeypatch, supabase) -> TestClient:
    monkeypatch.setattr(auth, 'get_supabase', lambda: supabase)

    app = FastAPI()

    @app.get('/me')
    async def me(request: Request, user: CurrentUser = Depends(get_current_user)):
        return {
            'id': user.id,
            'role': user.role,
            'state_user_id': request.state.user_id,
            'state_role': request.state.role,
        }

    @app.get('/customer')
    async def customer(user_id: str = Depends(get_customer)):
        return {'id': user_id}

    @app.get('/member')
    async def member(user_id: str = Depends(get_consented_customer)):
        return {'id': user_id}

    @app.get('/viewer')
    async def viewer(user_id: str = Depends(get_viewer)):
        return {'id': user_id}

    @app.get('/admin')
    async def admin(admin_id: str = Depends(get_admin)):
        return {'id': admin_id}

    async def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


def test_a_member_with_no_role_resolves_to_a_none_role(monkeypatch):
    client = _client(monkeypatch, _supabase_returning('u1', app_metadata={'provider': 'email'}))

    body = client.get('/me', headers=BEARER).json()

    assert body['id'] == 'u1'
    assert body['role'] is None


def test_the_admin_role_is_read_from_app_metadata(monkeypatch):
    client = _client(monkeypatch, _supabase_returning('u1', app_metadata={'role': 'admin'}))

    assert client.get('/me', headers=BEARER).json()['role'] == 'admin'


def test_id_and_role_are_exposed_on_request_state(monkeypatch):
    client = _client(monkeypatch, _supabase_returning('u1', app_metadata={'role': 'admin'}))

    body = client.get('/me', headers=BEARER).json()

    # The rate limiter and several handlers read request.state.user_id, so it must survive.
    assert body['state_user_id'] == 'u1'
    assert body['state_role'] == 'admin'


@pytest.mark.parametrize('app_metadata', [None, {}, {'role': None}])
def test_no_role_is_a_regular_member(monkeypatch, app_metadata):
    client = _client(monkeypatch, _supabase_returning('u1', app_metadata=app_metadata))

    response = client.get('/me', headers=BEARER)

    assert response.status_code == 200
    assert response.json()['role'] is None


@pytest.mark.parametrize(
    'role',
    [
        'superuser',  # not a known role
        'Admin',  # roles are case-sensitive
        '',
        ['admin'],  # unhashable, must be refused rather than blow up the lookup
        {'name': 'admin'},
        5,
    ],
)
def test_an_unrecognized_role_is_refused_with_a_403(monkeypatch, role):
    client = _client(monkeypatch, _supabase_returning('u1', app_metadata={'role': role}))

    response = client.get('/me', headers=BEARER)

    assert response.status_code == 403
    assert 'not recognized' in response.json()['detail']


def test_an_unrecognized_role_is_refused_on_member_and_admin_routes_too(monkeypatch):
    # Every dependency resolves the caller through get_current_user, so none of
    # them can be reached with a role the backend does not understand.
    _consent(monkeypatch, accepted=True)
    client = _client(monkeypatch, _supabase_returning('u1', app_metadata={'role': 'superuser'}))

    for path in ('/customer', '/member', '/viewer', '/admin'):
        assert client.get(path, headers=BEARER).status_code == 403, path


def test_a_missing_token_is_a_401(monkeypatch):
    client = _client(monkeypatch, _supabase_returning())

    assert client.get('/me').status_code == 401


def test_a_token_supabase_rejects_is_a_401(monkeypatch):
    rejecting = SimpleNamespace(auth=_FakeAuth(error=AuthApiError('bad jwt', 401, None)))
    client = _client(monkeypatch, rejecting)

    assert client.get('/me', headers=BEARER).status_code == 401


@pytest.mark.parametrize('result', [None, SimpleNamespace(user=None)])
def test_no_user_for_the_token_is_a_401_not_a_500(monkeypatch, result):
    # The 401 raised for this case used to be swallowed by the catch-all below it
    # and reported as a 500.
    client = _client(monkeypatch, SimpleNamespace(auth=_FakeAuth(result=result)))

    assert client.get('/me', headers=BEARER).status_code == 401


def test_an_unexpected_failure_is_a_500(monkeypatch):
    broken = SimpleNamespace(auth=_FakeAuth(error=RuntimeError('network down')))
    client = _client(monkeypatch, broken)

    assert client.get('/me', headers=BEARER).status_code == 500


def test_current_user_cannot_be_modified_after_it_is_built():
    user = CurrentUser(id='u1', role=None)

    with pytest.raises(FrozenInstanceError):
        user.role = 'admin'  # type: ignore[misc]


# Who may reach each kind of route, for a caller who HAS accepted the T&C. The
# default is closed: a route is open to the admin (a ghost) only if it uses
# get_viewer.
#   role   path        status
_ACCESS_MATRIX = [
    (None, '/customer', 200),
    (None, '/member', 200),
    (None, '/viewer', 200),
    (None, '/admin', 403),
    ('admin', '/customer', 403),
    ('admin', '/member', 403),
    ('admin', '/viewer', 200),
    ('admin', '/admin', 200),
]


@pytest.mark.parametrize(('role', 'path', 'expected'), _ACCESS_MATRIX)
def test_each_role_reaches_only_the_routes_it_should(monkeypatch, role, path, expected):
    _consent(monkeypatch, accepted=True)
    metadata = {'role': role} if role else {}
    client = _client(monkeypatch, _supabase_returning('u1', app_metadata=metadata))

    response = client.get(path, headers=BEARER)

    assert response.status_code == expected
    if expected == 200:
        assert response.json() == {'id': 'u1'}


@pytest.mark.parametrize('path', ['/customer', '/member', '/viewer', '/admin'])
def test_a_missing_token_is_refused_by_every_access_dependency(monkeypatch, path):
    _consent(monkeypatch, accepted=True)
    client = _client(monkeypatch, _supabase_returning('u1'))

    assert client.get(path).status_code == 401


def test_a_ghost_never_triggers_a_consent_lookup_on_a_member_or_viewer_route(monkeypatch):
    # A ghost has no profile, so there is nothing to look up -- and on the member
    # route the refusal must come before the lookup, not after it.
    asked = _consent(monkeypatch, accepted=True)
    client = _client(monkeypatch, _supabase_returning('u1', app_metadata={'role': 'admin'}))

    client.get('/viewer', headers=BEARER)
    client.get('/member', headers=BEARER)

    assert asked == []


def test_a_member_who_has_not_consented_is_refused_on_member_and_viewer_routes(monkeypatch):
    asked = _consent(monkeypatch, accepted=False)
    client = _client(monkeypatch, _supabase_returning('u1'))

    for path in ('/member', '/viewer'):
        response = client.get(path, headers=BEARER)
        assert response.status_code == 403, path
        assert 'Terms and Conditions' in response.json()['detail']

    assert asked == ['u1', 'u1']


def test_get_customer_does_not_require_consent(monkeypatch):
    # Profile creation goes through get_customer, and nobody has accepted anything
    # until their profile exists.
    asked = _consent(monkeypatch, accepted=False)
    client = _client(monkeypatch, _supabase_returning('u1'))

    assert client.get('/customer', headers=BEARER).status_code == 200
    assert asked == []
