MIN_PASSWORD_LENGTH = 8
PASSWORD_SPECIAL_CHARACTERS = r'[-#!$@£%^&*()_+|~=`{}\[\]:";\'<>?,./\\]'

REFRESH_TOKEN_EXPIRY_DAYS = 30

IMAGE_MIME_TO_EXT = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
}

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

PROFILES_PAGE_LIMIT = 20
COMMUNITIES_PAGE_LIMIT = 20
CONVERSATIONS_PAGE_LIMIT = 10
MESSAGES_PAGE_LIMIT = 10
REPLIES_PAGE_LIMIT = 5
EVENTS_PAGE_LIMIT = 20
CHAT_PREVIEWS_PAGE_LIMIT = 20
CHAT_MESSAGES_PAGE_LIMIT = 50
CHAT_PARTICIPANTS_PAGE_LIMIT = 20
CHAT_ADDABLE_PARTICIPANTS_PAGE_LIMIT = 20

MAX_NAME_LENGTH = 100
MAX_CITY_LENGTH = 100
MAX_BIO_LENGTH = 500
COMMUNITY_NAME_MAX_LENGTH = 100
COMMUNITY_DESCRIPTION_MAX_LENGTH = 500
CONVERSATION_TITLE_MIN_LENGTH = 3
CONVERSATION_TITLE_MAX_LENGTH = 120
CONVERSATION_BODY_MAX_LENGTH = 3000
EVENT_NAME_MAX_LENGTH = 100
EVENT_DESCRIPTION_MAX_LENGTH = 1000
EVENT_LOCATION_MAX_LENGTH = 500
EVENT_HOSTED_BY_ORG_NAME_MAX_LENGTH = 100
EVENT_HOSTED_BY_CONTACT_EMAIL_MAX_LENGTH = 254
EVENT_HOSTED_BY_CONTACT_PHONE_MAX_LENGTH = 20

# ── Moderation ─────────────────────────────────────────────────────────────
# Layer 2 toxicity classifier — runs locally via transformers (no API, no
# token, free). Swap the model id for any HF text-classification model; the
# detection logic is model-agnostic (see toxicity.py).
#   - unitary/toxic-bert ........... toxic/insult/threat/obscene/identity_hate
#   - KoalaAI/Text-Moderation ...... OpenAI-style categories, lighter
#   - martin-ha/toxic-comment-model  binary toxic, fastest
#   - facebook/roberta-hate-speech-dynabench-r4-target  hate-only
TOXICITY_MODEL = "unitary/toxic-bert"
# Minimum score (0..1) on any non-safe label required to remove content.
TOXICITY_THRESHOLD = 0.985
# Labels that mean "clean" across common moderation models (lowercased). Any
# label NOT in this set is treated as a violation when it clears the threshold.
TOXICITY_SAFE_LABELS = frozenset(
    {"nothate", "not_toxic", "non-toxic", "neutral", "ok", "safe", "clean", "no"}
)
# Guard pathological inputs before the tokenizer truncates to its max length.
TOXICITY_MAX_CHARS = 5000

# Temporary-ban policy: N auto-removed messages within the window → ban.
MODERATION_BAN_THRESHOLD = 3
MODERATION_BAN_WINDOW_HOURS = 24
MODERATION_BAN_DURATION_HOURS = 6

MODERATION_REPORT_REASON_MAX_LENGTH = 500
MODERATION_NOTIFICATIONS_PAGE_LIMIT = 20
