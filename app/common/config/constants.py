import os

# --- App ---
# Every value below is read at import time, which happens after main.py calls
# load_dotenv(). Validating here means a misconfigured deploy fails at startup
# rather than silently changing behaviour: `IS_PRODUCTION` alone gates all rate
# limiting and the refresh cookie's Secure flag, so a typo'd or missing ENV used
# to turn both off with no error, no log, and a healthy-looking process.
VALID_ENVS = frozenset({'production', 'development', 'test'})


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f'{name} must be set in environment variables.')
    return value


ENV = _require_env('ENV')
if ENV not in VALID_ENVS:
    raise RuntimeError(f'ENV must be one of {sorted(VALID_ENVS)}, got {ENV!r}.')

IS_PRODUCTION = ENV == 'production'

# Read here purely so a missing value fails startup; the consumers keep reading
# os.getenv so their call sites stay unchanged.
_require_env('FRONTEND_BASE_URL')
_require_env('DATABASE_URL')

# --- Proxying ---
# How many proxies of ours sit in front of the app, counted from the right of
# X-Forwarded-For. Anything further left in that header was written by the
# caller and must not be trusted. Render terminates TLS at one proxy; add one
# per additional layer (a CDN in front, say).
TRUSTED_PROXY_HOPS = int(os.getenv('TRUSTED_PROXY_HOPS', '1' if IS_PRODUCTION else '0'))
# A single-value header set by the edge, if the platform provides one
# (True-Client-IP on Render, CF-Connecting-IP behind Cloudflare). Preferred over
# X-Forwarded-For because a client cannot append to it.
TRUSTED_CLIENT_IP_HEADER = os.getenv('TRUSTED_CLIENT_IP_HEADER') or None

# --- Auth ---
MIN_PASSWORD_LENGTH = 8
PASSWORD_SPECIAL_CHARACTERS = r'[-#!$@£%^&*()_+|~=`{}\[\]:";\'<>?,./\\]'
REFRESH_TOKEN_EXPIRY_DAYS = 30

# --- Users ---
IMAGE_MIME_TO_EXT = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
}

# Hard ceiling on an uploaded avatar or community photo. Uploads are read fully
# into memory before they reach storage, so without a cap one authenticated
# request can exhaust the dyno -- the same memory ceiling that forced the
# torch/transformers removal. Five megabytes is well past any reasonable photo
# once the client has downscaled it.
MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
AGE_RANGES = {
    'Under 25': (0, 24),
    '25-29': (25, 29),
    '30-34': (30, 34),
    '35-39': (35, 39),
    '40-44': (40, 44),
    '45-49': (45, 49),
    '50-59': (50, 59),
    '60+': (60, 200),
}
MAX_NAME_LENGTH = 100
MAX_CITY_LENGTH = 100
MAX_BIO_LENGTH = 500

# Optional note on a connection request. Short on purpose: it is an
# introduction to help the recipient decide, not the conversation itself.
CONNECTION_NOTE_MAX_LENGTH = 300
PROFILES_PAGE_LIMIT = 20

# --- Communities ---
COMMUNITY_NAME_MAX_LENGTH = 100
COMMUNITY_DESCRIPTION_MAX_LENGTH = 500
CONVERSATION_TITLE_MIN_LENGTH = 3
CONVERSATION_TITLE_MAX_LENGTH = 120
CONVERSATION_BODY_MAX_LENGTH = 3000
COMMUNITIES_PAGE_LIMIT = 20
CONVERSATIONS_PAGE_LIMIT = 10
# The Home "get back into it" rail is a fixed shelf, not a browse surface.
RESUME_PAGE_LIMIT = 10
MESSAGES_PAGE_LIMIT = 10
REPLIES_PAGE_LIMIT = 5
# One invite fans out to one DM per recipient, so the cap is what keeps a single
# tap from becoming a broadcast. Ten is a handful of friends, not a mailing list.
COMMUNITY_INVITE_MAX_RECIPIENTS = 10
COMMUNITY_INVITE_MESSAGE = "Check out this community. I think you'd enjoy it!"
# Community photos live in their own bucket, keyed by community id, so a
# community's photo is never confused with a user's avatar.
COMMUNITY_IMAGES_BUCKET = 'community-images'

# --- Chats ---
CHAT_PREVIEWS_PAGE_LIMIT = 20
CHAT_MESSAGES_PAGE_LIMIT = 50
CHAT_PARTICIPANTS_PAGE_LIMIT = 20
CHAT_ADDABLE_PARTICIPANTS_PAGE_LIMIT = 20

# --- Events ---
EVENT_NAME_MAX_LENGTH = 100
EVENT_DESCRIPTION_MAX_LENGTH = 1000
EVENT_LOCATION_MAX_LENGTH = 500
EVENT_HOSTED_BY_ORG_NAME_MAX_LENGTH = 100
EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH = 254  # max email length as per internet standard (RFC 5321)
EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH = 20
EVENTS_PAGE_LIMIT = 20

# --- Moderation ---
# Temporary-ban policy: N auto-removed messages within the window -> ban
MODERATION_BAN_THRESHOLD = 3
MODERATION_BAN_WINDOW_HOURS = 24
MODERATION_BAN_DURATION_HOURS = 6
MODERATION_REPORT_REASON_MAX_LENGTH = 500
MODERATION_NOTIFICATIONS_PAGE_LIMIT = 20
