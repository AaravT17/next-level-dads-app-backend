from pydantic import BaseModel, Field, field_validator, model_validator
from uuid import UUID
from app.common.constants import (
    MAX_NAME_LENGTH,
    MAX_CITY_LENGTH,
    MAX_BIO_LENGTH,
    MAX_ICEBREAKER_ANSWER_LENGTH,
    CHILDREN_AGE_RANGES,
    GOALS,
    CONNECTION_STYLES,
    MATCH_PRIORITIES,
    PROVINCES,
    ICEBREAKER_PROMPT_SLUGS,
    MIN_INTERESTS,
    MAX_INTERESTS,
    MIN_ICEBREAKERS,
    MAX_ICEBREAKERS,
)
from app.common.types import ConnectionStatus
from datetime import datetime, date


class InterestItemResponse(BaseModel):
    id: UUID
    slug: str


class IcebreakerEntry(BaseModel):
    prompt_slug: str
    answer: str

    @field_validator('prompt_slug')
    @classmethod
    def validate_prompt_slug(cls, v: str) -> str:
        return _validate_icebreaker_prompt(v)

    @field_validator('answer')
    @classmethod
    def validate_answer(cls, v: str) -> str:
        return _validate_icebreaker_answer(v)


class UserBase(BaseModel):
    id: UUID
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    age: int = Field(ge=0, le=200)
    date_of_birth: date | None = None
    city: str = Field(min_length=1, max_length=MAX_CITY_LENGTH)
    province: str = Field(min_length=2, max_length=2)
    about: str = Field(min_length=1, max_length=MAX_BIO_LENGTH)
    avatar_url: str | None
    interests: list[InterestItemResponse] = []
    children_age_ranges: list[str] = []
    kid_count: int | None = Field(default=None, ge=0, lt=100)
    icebreakers: list[IcebreakerEntry] | None = None


class PreferencesData(BaseModel):
    marketing_emails_opt_in: bool = False


class LegalAcceptancesData(BaseModel):
    terms: bool = False
    privacy_policy: bool = False


class MeResponse(UserBase):
    goals: list[str] | None = None
    primary_goal: str | None = None
    connection_styles: list[str] | None = None
    match_priorities: list[str] | None = None
    is_admin: bool = False
    preferences: PreferencesData
    legal_acceptances: LegalAcceptancesData


class UserProfileResponse(UserBase):
    created_at: datetime
    connection_status: ConnectionStatus = None


class CreateProfileRequest(BaseModel):
    name: str
    date_of_birth: date
    city: str
    province: str
    about: str
    interests: list[UUID]
    children_age_ranges: list[str] = []
    kid_count: int = Field(ge=0, lt=100)
    goals: list[str]
    primary_goal: str
    connection_styles: list[str]
    match_priorities: list[str]
    icebreakers: list[IcebreakerEntry]
    accepted_terms: bool
    accepted_privacy_policy: bool
    marketing_emails_opt_in: bool = False

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v)

    @field_validator('city')
    @classmethod
    def validate_city(cls, v: str) -> str:
        return _validate_city(v)

    @field_validator('province')
    @classmethod
    def validate_province(cls, v: str) -> str:
        return _validate_province(v)

    @field_validator('about')
    @classmethod
    def validate_about(cls, v: str) -> str:
        return _validate_about(v)

    @field_validator('interests')
    @classmethod
    def validate_interests(cls, v: list[UUID]) -> list[UUID]:
        return _validate_interests(v)

    @field_validator('children_age_ranges')
    @classmethod
    def validate_children_age_ranges(cls, v: list[str]) -> list[str]:
        return _validate_children_age_ranges(v)

    @field_validator('goals')
    @classmethod
    def validate_goals(cls, v: list[str]) -> list[str]:
        return _validate_goals(v)

    @field_validator('primary_goal')
    @classmethod
    def validate_primary_goal(cls, v: str) -> str:
        return _validate_primary_goal(v)

    @field_validator('connection_styles')
    @classmethod
    def validate_connection_styles(cls, v: list[str]) -> list[str]:
        return _validate_connection_styles(v)

    @field_validator('match_priorities')
    @classmethod
    def validate_match_priorities(cls, v: list[str]) -> list[str]:
        return _validate_match_priorities(v)

    @field_validator('icebreakers')
    @classmethod
    def validate_icebreakers(cls, v: list[IcebreakerEntry]) -> list[IcebreakerEntry]:
        return _validate_icebreakers(v)


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    date_of_birth: date | None = None
    city: str | None = None
    province: str | None = None
    about: str | None = None
    interests: list[UUID] | None = None
    children_age_ranges: list[str] | None = None
    kid_count: int | None = Field(default=None, ge=0, lt=100)
    goals: list[str] | None = None
    primary_goal: str | None = None
    connection_styles: list[str] | None = None
    match_priorities: list[str] | None = None
    icebreakers: list[IcebreakerEntry] | None = None

    @model_validator(mode='after')
    def reject_nulls(self):
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f'{_FIELD_LABELS.get(field, field)} cannot be set to null.')
        return self

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        return _validate_name(v) if v is not None else v

    @field_validator('city')
    @classmethod
    def validate_city(cls, v: str | None) -> str | None:
        return _validate_city(v) if v is not None else v

    @field_validator('province')
    @classmethod
    def validate_province(cls, v: str | None) -> str | None:
        return _validate_province(v) if v is not None else v

    @field_validator('about')
    @classmethod
    def validate_about(cls, v: str | None) -> str | None:
        return _validate_about(v) if v is not None else v

    @field_validator('interests')
    @classmethod
    def validate_interests(cls, v: list[UUID] | None) -> list[UUID] | None:
        return _validate_interests(v) if v is not None else v

    @field_validator('children_age_ranges')
    @classmethod
    def validate_children_age_ranges(cls, v: list[str] | None) -> list[str] | None:
        return _validate_children_age_ranges(v) if v is not None else v

    @field_validator('goals')
    @classmethod
    def validate_goals(cls, v: list[str] | None) -> list[str] | None:
        return _validate_goals(v) if v is not None else v

    @field_validator('primary_goal')
    @classmethod
    def validate_primary_goal(cls, v: str | None) -> str | None:
        return _validate_primary_goal(v) if v is not None else v

    @field_validator('connection_styles')
    @classmethod
    def validate_connection_styles(cls, v: list[str] | None) -> list[str] | None:
        return _validate_connection_styles(v) if v is not None else v

    @field_validator('match_priorities')
    @classmethod
    def validate_match_priorities(cls, v: list[str] | None) -> list[str] | None:
        return _validate_match_priorities(v) if v is not None else v

    @field_validator('icebreakers')
    @classmethod
    def validate_icebreakers(cls, v: list[IcebreakerEntry] | None) -> list[IcebreakerEntry] | None:
        return _validate_icebreakers(v) if v is not None else v


class UpdatePreferencesRequest(BaseModel):
    marketing_emails_opt_in: bool


class UserStatsResponse(BaseModel):
    connections: int
    requests: int
    communities_joined: int
    events_registered_for: int


_FIELD_LABELS = {
    'name': 'Name',
    'date_of_birth': 'Date of birth',
    'city': 'City',
    'province': 'Province',
    'about': 'Bio',
    'interests': 'Interests',
    'children_age_ranges': 'Children age ranges',
    'kid_count': 'Number of kids',
    'goals': 'Goals',
    'primary_goal': 'Primary goal',
    'connection_styles': 'Connection styles',
    'match_priorities': 'Match priorities',
    'icebreakers': 'Icebreakers',
}


# --- Private helpers ---
def _validate_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError('Name cannot be empty.')
    if len(v) > MAX_NAME_LENGTH:
        raise ValueError(f'Name must be {MAX_NAME_LENGTH} characters or less.')
    return v


def _validate_city(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError('City cannot be empty.')
    if len(v) > MAX_CITY_LENGTH:
        raise ValueError(f'City must be {MAX_CITY_LENGTH} characters or less.')
    return v


def _validate_province(v: str) -> str:
    if v not in PROVINCES:
        raise ValueError('Invalid province.')
    return v


def _validate_about(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError('Bio cannot be empty.')
    if len(v) > MAX_BIO_LENGTH:
        raise ValueError(f'Bio must be {MAX_BIO_LENGTH} characters or less.')
    return v


def _validate_interests(v: list[UUID]) -> list[UUID]:
    v = list(set(v))  # deduplicate
    if len(v) < MIN_INTERESTS:
        raise ValueError(f'Please select at least {MIN_INTERESTS} interests.')
    if len(v) > MAX_INTERESTS:
        raise ValueError(f'You can select at most {MAX_INTERESTS} interests.')
    return v


def _validate_children_age_ranges(v: list[str]) -> list[str]:
    v = list(set(v))  # deduplicate
    if any(r not in CHILDREN_AGE_RANGES for r in v):
        raise ValueError('Invalid age range.')
    return v


def _validate_goals(v: list[str]) -> list[str]:
    v = list(set(v))  # deduplicate
    if not v:
        raise ValueError('Please select at least one goal.')
    if any(g not in GOALS for g in v):
        raise ValueError('Invalid goal.')
    return v


def _validate_primary_goal(v: str) -> str:
    if v not in GOALS:
        raise ValueError('Invalid primary goal.')
    return v


def _validate_connection_styles(v: list[str]) -> list[str]:
    v = list(set(v))  # deduplicate
    if not v:
        raise ValueError('Please select at least one connection style.')
    if any(s not in CONNECTION_STYLES for s in v):
        raise ValueError('Invalid connection style.')
    return v


def _validate_match_priorities(v: list[str]) -> list[str]:
    v = list(set(v))  # deduplicate
    if not v:
        raise ValueError('Please select at least one match priority.')
    if any(p not in MATCH_PRIORITIES for p in v):
        raise ValueError('Invalid match priority.')
    return v


def _validate_icebreaker_prompt(v: str) -> str:
    if v not in ICEBREAKER_PROMPT_SLUGS:
        raise ValueError('Invalid icebreaker prompt.')
    return v


def _validate_icebreaker_answer(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError('Answer cannot be empty.')
    if len(v) > MAX_ICEBREAKER_ANSWER_LENGTH:
        raise ValueError(f'Answer must be {MAX_ICEBREAKER_ANSWER_LENGTH} characters or less.')
    return v


def _validate_icebreakers(v: list[IcebreakerEntry]) -> list[IcebreakerEntry]:
    seen = set()
    deduped = []
    for entry in v:
        if entry.prompt_slug not in seen:
            seen.add(entry.prompt_slug)
            deduped.append(entry)
    v = deduped
    if len(v) < MIN_ICEBREAKERS:
        raise ValueError(f'Please provide at least {MIN_ICEBREAKERS} icebreaker.')
    if len(v) > MAX_ICEBREAKERS:
        raise ValueError(f'You can provide a maximum of {MAX_ICEBREAKERS} icebreakers.')
    return v
