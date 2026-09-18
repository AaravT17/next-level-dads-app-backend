"""Unit tests for reading credentials off a WebSocket handshake.

Both functions sit directly in front of authentication, and both parse
attacker-supplied strings, so the cases that matter are the malformed ones.
"""

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.ws.auth import BEARER_SUBPROTOCOL, extract_bearer_token, token_expiry


def _jwt(payload: dict) -> str:
    """A structurally valid JWT. The signature is never checked by these helpers."""

    def segment(data: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
        return raw.rstrip('=')  # JWTs carry no padding

    return f'{segment({"alg": "HS256"})}.{segment(payload)}.signature'


class TestExtractBearerToken:
    def test_reads_the_token_from_a_well_formed_offer(self):
        assert extract_bearer_token(f'{BEARER_SUBPROTOCOL}, abc.def.ghi') == 'abc.def.ghi'

    def test_tolerates_missing_whitespace_after_the_comma(self):
        assert extract_bearer_token(f'{BEARER_SUBPROTOCOL},abc.def.ghi') == 'abc.def.ghi'

    @pytest.mark.parametrize(
        'header',
        [
            None,
            '',
            '   ',
            'abc.def.ghi',  # token with no marker
            BEARER_SUBPROTOCOL,  # marker with no token
            f'{BEARER_SUBPROTOCOL}, a, b',  # more than one value
            f'graphql-ws, {BEARER_SUBPROTOCOL}',  # marker not first
            'Bearer, abc',  # the marker is case-sensitive
        ],
    )
    def test_rejects_anything_but_the_exact_shape(self, header):
        # Returning None means the socket is closed rather than opened with a
        # value guessed out of a malformed header.
        assert extract_bearer_token(header) is None


class TestTokenExpiry:
    def test_reads_the_exp_claim(self):
        expected = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)
        assert token_expiry(_jwt({'exp': expected.timestamp()})) == expected

    @pytest.mark.parametrize(
        'token',
        [
            'not-a-jwt',
            'only.two',
            'a.b.c.d',
            _jwt({}),  # no exp claim
        ],
    )
    def test_returns_none_when_there_is_no_readable_expiry(self, token):
        # None means "no watchdog", not "already expired" -- a token we cannot
        # read the expiry of must not silently close a working socket.
        assert token_expiry(token) is None

    def test_returns_none_for_an_undecodable_payload(self):
        assert token_expiry('header.!!!not-base64!!!.sig') is None

    @pytest.mark.parametrize('exp', ['soon', None, True, [], {}])
    def test_returns_none_when_exp_is_not_a_number(self, exp):
        # `True` is in this list on purpose: bool is a subclass of int, and
        # datetime.fromtimestamp(True) would happily return 1970.
        assert token_expiry(_jwt({'exp': exp})) is None

    def test_returns_none_for_an_out_of_range_timestamp(self):
        assert token_expiry(_jwt({'exp': 10**20})) is None
