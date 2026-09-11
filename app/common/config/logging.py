import logging
import os

_DEFAULT_LEVEL = 'INFO'


def configure_logging() -> None:
    """Attach a root handler so log output is usable.

    Nothing called basicConfig, so the root logger had no handler and Python's
    "last resort" fallback took over: it emits WARNING and above to stderr with
    the bare message and nothing else -- no timestamp, no level, no logger name.
    Everything below WARNING was dropped outright, including the INFO record
    `moderate_content` writes for every piece of content it removes, which is
    the audit trail for automatic moderation.

    LOG_LEVEL overrides the default for a noisy debugging session.
    """
    level = os.getenv('LOG_LEVEL', _DEFAULT_LEVEL).upper()
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)-8s %(name)s: %(message)s',
        force=True,
    )
