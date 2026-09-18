from fastapi import HTTPException, status
from pydantic import ValidationError

INVALID_PARAMS_DETAIL = 'Invalid request parameters.'


def value_error_to_http(exc: ValueError, server_detail: str) -> HTTPException:
    """Map a caught ValueError to the status it actually deserves.

    `pydantic.ValidationError` subclasses `ValueError`, so one `except ValueError`
    clause catches two unrelated things: a malformed UUID in the path, which is
    the caller's fault and a 400, and a response model that would not build from
    a database row, which is ours and a 500. Treating the second as a 400 hides
    real server faults from error budgets, and passing `str(exc)` through for it
    hands the caller Pydantic's field paths, the offending input value and a
    docs URL.

    Callers keep their own 500 wording so the message still names the operation
    that failed.
    """
    if isinstance(exc, ValidationError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=server_detail,
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=INVALID_PARAMS_DETAIL,
    )
