"""Who may open the chat WebSocket.

A handshake has no response to attach an HTTP error to, so every refusal is the
same thing: the socket is closed with 1008 before it is accepted. The cases that
matter are the ones that must be refused -- a caller who cannot be identified, a
role the backend does not recognize, a ghost, a member who has not consented --
and one that must get through, so that a socket which refuses everyone cannot
pass. The resolver, the consent lookup and the connection registry are stand-ins.
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.modules.ws.router as ws_router
from app.common.dependencies.auth import CurrentUser
from app.modules.ws.auth import BEARER_SUBPROTOCOL
from main import app as api

POLICY_VIOLATION = 1008


class _Conn:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_exc):
        return False


class _Pool:
    def acquire(self):
        return _Conn()


def _open(monkeypatch, resolved, *, consented=True):
    """Try to open the socket as `resolved`: a CurrentUser, None, or an exception for the resolver to raise.

    Returns (first message if accepted, close code if refused, ids the consent lookup was asked about).
    """
    asked: list[str] = []

    async def resolve_current_user(_token):
        if isinstance(resolved, Exception):
            raise resolved
        return resolved

    async def check_consent(_conn, user_id):
        asked.append(user_id)
        return consented

    async def register_connection(_user_id, _connection_id, ws, subprotocol=None):
        await ws.accept(subprotocol=subprotocol)

    async def unregister_connection(*_args):
        return None

    monkeypatch.setattr(ws_router, 'resolve_current_user', resolve_current_user)
    monkeypatch.setattr(ws_router, 'check_consent', check_consent)
    monkeypatch.setattr(ws_router, 'register_connection', register_connection)
    monkeypatch.setattr(ws_router, 'unregister_connection', unregister_connection)
    monkeypatch.setattr(ws_router, 'is_user_initialized', lambda _user_id: True)
    monkeypatch.setattr(api.state, 'pool', _Pool(), raising=False)

    client = TestClient(api)
    try:
        with client.websocket_connect('/api/ws/', subprotocols=[BEARER_SUBPROTOCOL, 'token']) as ws:
            return ws.receive_json(), None, asked
    except WebSocketDisconnect as refused:
        return None, refused.code, asked


def test_a_consented_member_is_accepted(monkeypatch):
    message, code, _ = _open(monkeypatch, CurrentUser(id='u1', role=None))

    assert message == {'type': 'ws:ready'}
    assert code is None


@pytest.mark.parametrize(
    'resolved',
    [None, HTTPException(403, 'role'), RuntimeError('supabase down')],
    ids=['unknown token', 'unrecognized role', 'resolver failure'],
)
def test_a_caller_who_cannot_be_identified_is_refused(monkeypatch, resolved):
    message, code, asked = _open(monkeypatch, resolved)

    assert (message, code) == (None, POLICY_VIOLATION)
    assert asked == []


def test_a_ghost_is_refused_before_any_consent_lookup(monkeypatch):
    message, code, asked = _open(monkeypatch, CurrentUser(id='u1', role='admin'))

    assert (message, code) == (None, POLICY_VIOLATION)
    assert asked == []


def test_a_member_who_has_not_consented_is_refused(monkeypatch):
    message, code, asked = _open(monkeypatch, CurrentUser(id='u1', role=None), consented=False)

    assert (message, code) == (None, POLICY_VIOLATION)
    assert asked == ['u1']
