"""Reading credentials off a WebSocket handshake.

Both helpers are pure so they can be tested without a socket or a network.
"""

import base64
import binascii
import json
from datetime import UTC, datetime

# The browser WebSocket API cannot set request headers, but it can offer
# subprotocols -- and those travel in `Sec-WebSocket-Protocol`, which is a
# header. Offering ['bearer', '<jwt>'] is the established way to get a
# credential onto a socket without putting it in the URL, where every proxy and
# access log in the path would record it.
BEARER_SUBPROTOCOL = 'bearer'


def extract_bearer_token(header_value: str | None) -> str | None:
    """Pull the token out of an offered `bearer, <token>` subprotocol list.

    Returns None unless the list is exactly the marker followed by one value.
    Being strict here is deliberate: anything else is not a client of ours.
    """
    if not header_value:
        return None

    offered = [part.strip() for part in header_value.split(',') if part.strip()]
    if len(offered) != 2 or offered[0] != BEARER_SUBPROTOCOL:
        return None
    return offered[1]


def token_expiry(token: str) -> datetime | None:
    """The `exp` claim, or None if the token has no readable one.

    The signature is *not* checked here -- Supabase has already verified the
    token by the time this runs, and re-verifying would mean holding the signing
    key. This only reads a claim from a token already established as genuine, so
    that the socket can be closed when it lapses.
    """
    parts = token.split('.')
    if len(parts) != 3:
        return None

    payload = parts[1]
    # JWT uses base64url without padding; b64decode requires it.
    payload += '=' * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None

    exp = claims.get('exp') if isinstance(claims, dict) else None
    if not isinstance(exp, int | float) or isinstance(exp, bool):
        return None
    try:
        return datetime.fromtimestamp(exp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
