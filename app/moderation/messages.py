"""Human-readable copy for moderation notifications.

Kept separate from orchestration and SQL so the wording is easy to tweak.
"""

from app.moderation.models import ContentType, ModerationLayer

_CONTENT_NOUN: dict[ContentType, str] = {
    ContentType.CONVERSATION: "post",
    ContentType.MESSAGE: "reply",
    ContentType.REPLY: "reply",
}

_REMOVAL_REASON: dict[ModerationLayer, str] = {
    ModerationLayer.PROFANITY: "it violates our community language policy",
    ModerationLayer.HATE_SPEECH: "it violates our community conduct policy",
    ModerationLayer.REPORT: "it was flagged for review under our community guidelines",
}

# Appended to automated removals so members know AI is involved and can err.
_AI_DISCLAIMER = (
    " This was reviewed using automated tools, including AI, which can "
    "sometimes get it wrong — thanks for your understanding, and please keep "
    "things considerate."
)


def build_removal_message(content_type: ContentType, layer: ModerationLayer) -> str:
    noun = _CONTENT_NOUN.get(content_type, "message")
    why = _REMOVAL_REASON.get(layer, "it violates our community guidelines")
    return f"Your {noun} was removed because {why}.{_AI_DISCLAIMER}"


def build_moderator_removal_message(content_type: ContentType) -> str:
    noun = _CONTENT_NOUN.get(content_type, "message")
    return (
        f"Your {noun} was removed by a moderator because it violates our "
        "community guidelines."
    )


def build_ban_message(duration_hours: int) -> str:
    return (
        f"Your posting access has been temporarily suspended for {duration_hours} "
        "hours following repeated violations of our community guidelines. You'll be "
        "able to post again once the suspension period ends."
    )
