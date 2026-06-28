"""Layer 2 moderation: local toxicity / hate-speech classification.

Runs a HuggingFace text-classification model **in-process** via transformers —
no API and no token, so it is free. Model weights are downloaded once to the
local HF cache on first use.

The model is loaded lazily as a process-wide singleton (guarded by a lock) and
every inference runs in a worker thread so the CPU-bound forward pass never
blocks the event loop. This layer only ever runs inside the moderation
background task, so the latency stays off the posting path entirely.

Detection is model-agnostic: any predicted label that is not in
`TOXICITY_SAFE_LABELS` and clears `TOXICITY_THRESHOLD` flags the content. That
lets the model be swapped via a single constant.

Fail-open policy: a missing dependency, failed model load, or inference error
returns a clean result (logged) — transient failures must never destroy
content. The local profanity layer still catches the obvious cases.
"""

import asyncio
import logging

from app.config.constants import (
    TOXICITY_MAX_CHARS,
    TOXICITY_MODEL,
    TOXICITY_SAFE_LABELS,
    TOXICITY_THRESHOLD,
)
from app.moderation.models import ModerationLayer, ModerationResult

logger = logging.getLogger(__name__)

_pipeline = None
_load_failed = False
_load_lock = asyncio.Lock()


def _build_pipeline():
    """Construct the transformers pipeline (blocking; runs in a thread)."""
    from transformers import pipeline

    return pipeline("text-classification", model=TOXICITY_MODEL, top_k=None)


async def _get_pipeline():
    """Return the cached pipeline, loading it once on first use."""
    global _pipeline, _load_failed
    if _pipeline is not None or _load_failed:
        return _pipeline
    async with _load_lock:
        if _pipeline is None and not _load_failed:
            try:
                _pipeline = await asyncio.to_thread(_build_pipeline)
                logger.info("Loaded local toxicity model '%s'", TOXICITY_MODEL)
            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                _load_failed = True
                logger.warning(
                    "Could not load toxicity model '%s': %s; layer disabled.",
                    TOXICITY_MODEL,
                    exc,
                )
    return _pipeline


async def warmup() -> None:
    """Preload the model (e.g. at startup) so the first post isn't slow."""
    await _get_pipeline()


def _top_violation(predictions: object) -> tuple[str | None, float]:
    """Find the highest-scoring non-safe label in a prediction payload.

    Handles both `[[{...}]]` (batched) and `[{...}]` shapes.
    """
    if isinstance(predictions, list) and predictions and isinstance(predictions[0], list):
        predictions = predictions[0]
    if not isinstance(predictions, list):
        return None, 0.0

    worst_label: str | None = None
    worst_score = 0.0
    for entry in predictions:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).lower()
        if label in TOXICITY_SAFE_LABELS:
            continue
        score = float(entry.get("score") or 0.0)
        if score > worst_score:
            worst_label, worst_score = label, score
    return worst_label, worst_score


async def check_toxicity(text: str) -> ModerationResult:
    """Return a flagged result when the classifier is confident `text` is toxic."""
    if not text:
        return ModerationResult.clean()

    pipe = await _get_pipeline()
    if pipe is None:
        return ModerationResult.clean()

    try:
        predictions = await asyncio.to_thread(
            lambda: pipe(text[:TOXICITY_MAX_CHARS], truncation=True)
        )
    except Exception as exc:  # noqa: BLE001 - fail open on inference errors
        logger.warning("Toxicity inference failed: %s", exc)
        return ModerationResult.clean()

    label, score = _top_violation(predictions)
    if label is None:
        return ModerationResult.clean()
    if score < TOXICITY_THRESHOLD:
        # Below the removal threshold but still record the score for audit.
        return ModerationResult(flagged=False, score=score)

    return ModerationResult(
        flagged=True,
        layer=ModerationLayer.HATE_SPEECH,
        reason=label,
        score=score,
    )
