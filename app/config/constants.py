MIN_PASSWORD_LENGTH = 8

PASSWORD_SPECIAL_CHARACTERS = r'[-#!$@£%^&*()_+|~=`{}\[\]:";\'<>?,./\\]'

REFRESH_TOKEN_EXPIRY_DAYS = 30

MAX_BIO_LENGTH = 200

IMAGE_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
}

AGE_RANGES = {
    "Under 25": (0, 24),
    "25-29": (25, 29),
    "30-34": (30, 34),
    "35-39": (35, 39),
    "40-44": (40, 44),
    "45-49": (45, 49),
    "50-59": (50, 59),
    "60+": (60, 200),
}

DISCOVER_PROFILES_PAGE_LIMIT = 20
