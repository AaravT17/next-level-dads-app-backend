"""Unit tests for connection status resolution.

`resolve_connection_status` is pure and needs no database, which makes it the
natural first test in this repo. It also carries real weight: the value it
returns drives which button a profile card shows, so getting the direction
wrong offers "Accept" to the person who sent the request.
"""

from uuid import uuid4

import pytest

from app.modules.connections.utils import resolve_connection_status

ME = uuid4()
THEM = uuid4()


def test_accepted_reads_as_connected_regardless_of_direction():
    assert resolve_connection_status(ME, ME, 'accepted') == 'connected'
    assert resolve_connection_status(ME, THEM, 'accepted') == 'connected'


def test_pending_direction_depends_on_who_asked():
    # The requester sees an outgoing request; the recipient sees one to accept.
    assert resolve_connection_status(ME, ME, 'pending') == 'pending_outgoing'
    assert resolve_connection_status(ME, THEM, 'pending') == 'pending_incoming'


def test_blocked_reads_as_blocked_from_either_side():
    assert resolve_connection_status(ME, ME, 'blocked') == 'blocked'
    assert resolve_connection_status(ME, THEM, 'blocked') == 'blocked'


def test_no_connection_row_resolves_to_none():
    assert resolve_connection_status(ME, None, None) is None


@pytest.mark.parametrize('unknown', ['', 'declined', 'ACCEPTED', 'Pending'])
def test_unrecognised_status_resolves_to_none_rather_than_guessing(unknown):
    # Status is read straight from the database. An unmapped value must not fall
    # through to a connected-looking state.
    assert resolve_connection_status(ME, THEM, unknown) is None
