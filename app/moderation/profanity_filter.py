"""Layer 1 moderation: fast, local profanity filtering.

Uses the `better-profanity` package (the Python equivalent of the JS
`bad-words` library). Runs entirely in-process with no network call, so it is
cheap enough to run on every post. The import is guarded so a missing optional
dependency degrades gracefully (layer skipped) instead of crashing the app.
"""

import logging

from app.moderation.models import ModerationLayer, ModerationResult

logger = logging.getLogger(__name__)

try:
    from better_profanity import profanity as _profanity

    _profanity.load_censor_words()
    _AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    logger.warning(
        "better-profanity is not installed; profanity layer disabled. "
        "Run `pip install better-profanity`."
    )
    _AVAILABLE = False


def _matched_word(text: str) -> str | None:
    """Best-effort extraction of the first offending token, for the audit log."""
    for token in text.split():
        if _profanity.contains_profanity(token):
            return token.strip(".,!?;:\"'").lower()
    return None


def check_profanity(text: str) -> ModerationResult:
    """Return a flagged result when `text` contains banned words."""
    if not _AVAILABLE or not text:
        return ModerationResult.clean()

    if not _profanity.contains_profanity(text):
        return ModerationResult.clean()

    return ModerationResult(
        flagged=True,
        layer=ModerationLayer.PROFANITY,
        reason=_matched_word(text) or "profanity",
    )
