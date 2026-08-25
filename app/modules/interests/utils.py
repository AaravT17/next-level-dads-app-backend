import re


def normalize_interest(interest: str) -> str:
    return re.sub(r"\s+", " ", interest).strip().title()
