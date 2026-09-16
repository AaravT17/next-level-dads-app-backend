"""A reply to a message is activity in its thread.

Before the visit-tracking work, `reply_to_message` never moved
`conversations.last_activity_at` -- only top-level messages did. That is invisible
in the reply's own response, and it is wrong in three places at once: the
community's "Most Active" sort, the home feed's ordering, and the per-community
"active since you last visited" count, all of which read that column. A thread
could take forty replies and still sink as though nothing had happened.

This drives the service function against a stub connection rather than a
database, so it asserts the thing that actually regressed: that the write
happens, and that it happens in the same transaction as the insert.

The coroutines are run directly instead of through an async pytest plugin. The
repo has no async tests and requirements-dev.txt is deliberately just pytest and
ruff, which is not worth changing for three cases that await nothing real.
"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.communities import service

MESSAGE_ID = uuid4()
CONVERSATION_ID = uuid4()
AUTHOR_ID = uuid4()
REPLY_ID = uuid4()
NOW = datetime.now(timezone.utc)


class _Transaction:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        self._conn.calls.append(('BEGIN', None))
        return self

    async def __aexit__(self, *exc):
        self._conn.calls.append(('COMMIT', None))
        return False


class _StubConnection:
    """Records the calls `reply_to_message` makes, in order."""

    def __init__(self, parent_conversation_id=CONVERSATION_ID):
        self._parent = parent_conversation_id
        self.calls: list[tuple[str, object]] = []

    def transaction(self):
        return _Transaction(self)

    async def fetchval(self, query, *args):
        self.calls.append(('fetchval', query))
        return self._parent

    async def execute(self, query, *args):
        self.calls.append(('execute', query))

    async def fetchrow(self, query, *args):
        self.calls.append(('fetchrow', query))
        # insert_reply reads ['id']; the final read builds the response.
        return {
            'id': REPLY_ID,
            'message_id': MESSAGE_ID,
            'body': 'me too',
            'created_at': NOW,
            'updated_at': NOW,
            'is_deleted': False,
            'deleted_at': None,
            'deleted_by_moderator': False,
            'heart_count': 0,
            'is_hearted': False,
            'has_pending_report': False,
            'author_id': AUTHOR_ID,
            'author_name': 'A Dad',
            'author_avatar_url': None,
            'author_about': None,
        }


def _executed(conn) -> str:
    return ' '.join(q for kind, q in conn.calls if kind == 'execute' and q)


def _reply(conn):
    return asyncio.run(service.reply_to_message(conn, MESSAGE_ID, AUTHOR_ID, 'me too'))


def test_replying_moves_the_threads_last_activity():
    conn = _StubConnection()

    _reply(conn)

    assert 'UPDATE conversations' in _executed(conn)
    assert 'last_activity_at = NOW()' in _executed(conn)


def test_the_touch_shares_the_inserts_transaction():
    # A reply that lands without its thread moving would sit unreachable at the
    # bottom of every sort, so the two writes commit together or not at all.
    conn = _StubConnection()

    _reply(conn)

    kinds = [kind for kind, _ in conn.calls]
    assert 'BEGIN' in kinds and 'COMMIT' in kinds
    begin, commit = kinds.index('BEGIN'), kinds.index('COMMIT')
    writes = [i for i, (kind, q) in enumerate(conn.calls) if kind == 'execute']
    assert writes, 'expected the insert and the touch to run as writes'
    assert all(begin < i < commit for i in writes)


def test_a_reply_to_a_missing_or_deleted_message_is_rejected():
    # The lookup now returns the parent id rather than a boolean; None has to
    # keep meaning 404 rather than being treated as a found thread.
    conn = _StubConnection(parent_conversation_id=None)

    with pytest.raises(HTTPException) as excinfo:
        _reply(conn)

    assert excinfo.value.status_code == 404
    assert _executed(conn) == '', 'nothing should be written when the parent is gone'
