import os

# --- App ---
IS_PRODUCTION = os.getenv('ENV') == 'production'

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
PROFILES_PAGE_LIMIT = 20
MIN_INTERESTS = 3
MAX_INTERESTS = 7
MIN_ICEBREAKERS = 1
MAX_ICEBREAKERS = 3
MAX_ICEBREAKER_ANSWER_LENGTH = 250

PROVINCES = {'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'SK', 'YT'}

GOALS = {'dad-friends', 'events', 'playdates', 'advice', 'communities', 'resources', 'experts'}

CONNECTION_STYLES = {'close', 'casual', 'activity', 'family', 'playdate', 'gets-it'}

MATCH_PRIORITIES = {'nearby', 'kid-ages', 'interests', 'connection-type', 'age', 'no-preference'}

INTEREST_SLUGS = {
    'sports', 'fitness', 'golf', 'outdoors', 'gaming', 'food', 'music',
    'movies-tv', 'comedy', 'theatre', 'true-crime', 'travel', 'tech', 'cars',
    'reading', 'photography', 'podcasts', 'art', 'fashion', 'collectibles',
    'history', 'diy', 'board-games', 'pets', 'gardening', 'volunteering',
    'finance', 'entrepreneurship', 'faith-spirituality', 'health-wellness',
}

ICEBREAKER_PROMPT_SLUGS = {
    'fatherhood-taught-me', 'favourite-thing-with-kids', 'wish-id-known',
    'dad-skill', 'hoping-to-meet', 'get-along-if', 'ideal-hangout',
    'always-down-to', 'life-goal', 'ask-me-about', 'currently-obsessed',
    'perfect-weekend', 'want-to-learn', 'wont-shut-up', 'unpopular-opinion',
    'way-to-my-heart', 'dad-joke', 'weirdly-competitive', 'hill-ill-die-on',
    'guilty-pleasure', 'dream-dinner-guest', 'settle-this',
    'dream-travel-destination', 'bucket-list', 'party-story', 'fun-fact',
    'proudest-achievement', 'two-truths-and-a-lie', 'biggest-pet-peeve',
    'random-fact-i-love', 'favourite-quote', 'dad-stereotype',
}

# --- Communities ---
COMMUNITY_NAME_MAX_LENGTH = 100
COMMUNITY_DESCRIPTION_MAX_LENGTH = 500
CONVERSATION_TITLE_MIN_LENGTH = 3
CONVERSATION_TITLE_MAX_LENGTH = 120
CONVERSATION_BODY_MAX_LENGTH = 3000
COMMUNITIES_PAGE_LIMIT = 20
CONVERSATIONS_PAGE_LIMIT = 10
MESSAGES_PAGE_LIMIT = 10
REPLIES_PAGE_LIMIT = 5

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
