import re
from app.common.config.constants import MIN_PASSWORD_LENGTH, PASSWORD_SPECIAL_CHARACTERS


def validate_password_strength(pwd: str) -> str:
    """
    Validates the strength of a password.
    A strong password must meet the following criteria:
    - At least 8 characters long
    - Contains at least one digit
    - Contains at least one uppercase letter
    - Contains at least one lowercase letter
    - Contains at least one special character
    """
    if len(pwd) < MIN_PASSWORD_LENGTH:
        raise ValueError(f'Password must be at least {MIN_PASSWORD_LENGTH} characters long')
    if not any(char.isdigit() for char in pwd):
        raise ValueError('Password must contain at least one digit')
    if not any(char.isalpha() and char.isupper() for char in pwd):
        raise ValueError('Password must contain at least one uppercase letter')
    if not any(char.isalpha() and char.islower() for char in pwd):
        raise ValueError('Password must contain at least one lowercase letter')
    if not re.search(PASSWORD_SPECIAL_CHARACTERS, pwd):
        raise ValueError('Password must contain at least one special character')
    return pwd


def strip_email(email: str) -> str:
    """Strips whitespace from the email and validates that it is a non-empty string."""
    if not isinstance(email, str):
        raise ValueError('Email must be a string')
    email = email.strip()
    if len(email) == 0:
        raise ValueError('Email cannot be empty')
    return email
