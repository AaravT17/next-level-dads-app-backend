"""What login, the OAuth session exchange and refresh hand back.

All three return the same `SessionResponse` -- the access token and the caller's
role -- and all three refuse an unrecognized role before any cookie is set, so
nobody is handed a session that would be refused on every request afterwards.
Supabase is replaced with a fake; nothing here connects to anything.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.modules.auth.service as auth_service
from main import app as api

ENDPOINTS = ['login', 'oauth session', 'refresh']


def _supabase(app_metadata):
    user = SimpleNamespace(id='u1', app_metadata=app_metadata)
    session = SimpleNamespace(access_token='new-access', refresh_token='new-refresh', user=user)

    async def sign_in_with_password(_credentials):
        return SimpleNamespace(session=session)

    async def refresh_session(_refresh_token):
        return SimpleNamespace(session=session)

    async def get_user(_access_token):
        return SimpleNamespace(user=user)

    return SimpleNamespace(
        auth=SimpleNamespace(
            sign_in_with_password=sign_in_with_password,
            refresh_session=refresh_session,
            get_user=get_user,
        )
    )


def _call(monkeypatch, endpoint, app_metadata):
    monkeypatch.setattr(auth_service, 'get_supabase', lambda: _supabase(app_metadata))
    client = TestClient(api)

    if endpoint == 'login':
        return client.post('/api/auth/login', json={'email': 'dad@example.com', 'password': 'password'})
    if endpoint == 'oauth session':
        return client.post('/api/auth/oauth/session', json={'access_token': 'a', 'refresh_token': 'r'})
    client.cookies.set('refresh_token', 'old-refresh')
    return client.post('/api/auth/refresh')


@pytest.mark.parametrize('endpoint', ENDPOINTS)
@pytest.mark.parametrize(
    ('app_metadata', 'role'),
    [(None, None), ({}, None), ({'role': 'admin'}, 'admin')],
    ids=['no metadata', 'no role', 'admin'],
)
def test_each_endpoint_returns_the_access_token_and_the_role(monkeypatch, endpoint, app_metadata, role):
    response = _call(monkeypatch, endpoint, app_metadata)

    assert response.status_code == 200
    assert response.json() == {'access_token': 'new-access', 'role': role}
    assert response.headers['set-cookie'].startswith('refresh_token=new-refresh')


@pytest.mark.parametrize('endpoint', ENDPOINTS)
def test_each_endpoint_refuses_an_unrecognized_role_and_sets_no_cookie(monkeypatch, endpoint):
    response = _call(monkeypatch, endpoint, {'role': 'superuser'})

    assert response.status_code == 403
    assert 'set-cookie' not in response.headers
    assert 'access_token' not in response.json()
