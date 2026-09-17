"""The conversation type is a closed set now, not free text.

It used to be whatever the author typed, which is why the field is a bare TEXT
column with no constraint and why old rows may hold anything. Validation lives
in the request model rather than the database for exactly that reason: new
posts are checked, existing ones are left alone.

`ConversationCreate` is a plain Pydantic model, so this needs no database and
no client.
"""

import pytest
from pydantic import ValidationError

from app.common.config.constants import CONVERSATION_PROMPT_TYPES
from app.modules.communities.models import ConversationCreate

VALID_POST = {'title': 'Bedtime is a battle', 'body': 'Any advice?'}


def _create(**overrides) -> ConversationCreate:
    return ConversationCreate(**{**VALID_POST, **overrides})


@pytest.mark.parametrize('prompt_type', sorted(CONVERSATION_PROMPT_TYPES))
def test_every_offered_type_is_accepted(prompt_type):
    # The picker is built from this same set on the client, so anything it can
    # send has to survive the round trip.
    assert _create(prompt_type=prompt_type).prompt_type == prompt_type


def test_the_type_is_optional():
    assert _create().prompt_type is None
    assert _create(prompt_type=None).prompt_type is None


@pytest.mark.parametrize('blank', ['', '   ', '\n'])
def test_a_blank_choice_means_no_type_rather_than_a_sixth_one(blank):
    # A select left on its placeholder posts an empty string. Storing that
    # would put an empty chip on the card.
    assert _create(prompt_type=blank).prompt_type is None


def test_casing_and_padding_are_normalised():
    # The stored value is the slug; the client owns how it is capitalised.
    assert _create(prompt_type='  Question  ').prompt_type == 'question'


@pytest.mark.parametrize('rejected', ['rant', 'QUESTION!', 'question ?', 'tip', 'story time'])
def test_anything_outside_the_set_is_refused(rejected):
    # Free text is what this replaced; a near-miss must not quietly become a
    # sixth kind of chip.
    with pytest.raises(ValidationError):
        _create(prompt_type=rejected)


def test_the_set_is_small_enough_to_be_a_picker():
    # A choice of five is a row of buttons; a choice of thirty is free text
    # wearing a costume, and the reason the field was closed in the first place.
    assert 2 <= len(CONVERSATION_PROMPT_TYPES) <= 8


def test_every_type_is_a_plain_lowercase_slug():
    # These are stored values that the client maps to display labels, so a
    # capital or a space here would mean the same kind stored two ways.
    for prompt_type in CONVERSATION_PROMPT_TYPES:
        assert prompt_type == prompt_type.strip().lower()
        assert ' ' not in prompt_type
