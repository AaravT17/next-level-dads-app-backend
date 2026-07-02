"""Layer 2 moderation: toxicity classification (disabled).

The ML-based hate-speech classifier (transformers/torch) has been removed to
stay within Render's memory limits. The profanity filter (layer 1) still runs.
This layer always returns clean so the rest of the moderation pipeline is
unaffected.
"""

from app.moderation.models import ModerationResult


async def warmup() -> None:
    pass


async def check_toxicity(text: str) -> ModerationResult:
    return ModerationResult.clean()
