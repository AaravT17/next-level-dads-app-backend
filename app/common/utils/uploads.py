from fastapi import HTTPException, Request, UploadFile, status

from app.common.config.constants import IMAGE_MIME_TO_EXT

# Leading bytes every file of a given type must start with. The MIME type on an
# upload is whatever the client typed; these are what the file actually is.
_IMAGE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    'image/png': (b'\x89PNG\r\n\x1a\n',),
    'image/jpeg': (b'\xff\xd8\xff',),
    'image/jpg': (b'\xff\xd8\xff',),
}

_CHUNK_SIZE = 64 * 1024


def _too_large(max_bytes: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail=f'File is too large. Maximum size is {max_bytes // (1024 * 1024)} MB.',
    )


async def read_capped_upload(request: Request, upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload into memory, refusing anything over `max_bytes`.

    Two checks rather than one. Content-Length rejects an honest oversized
    upload before a byte is read, which is the common case and the cheap one.
    The chunked loop then enforces the same ceiling against a client that lies
    about or omits the header — `await upload.read()` with no argument would
    pull the whole body into memory regardless of what the header claimed.
    """
    content_length = request.headers.get('content-length')
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise _too_large(max_bytes)
        except ValueError:
            # An unparseable header tells us nothing; the loop below still holds.
            pass

    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise _too_large(max_bytes)
        chunks.append(chunk)
    return b''.join(chunks)


def assert_image_contents(file_contents: bytes, mime_type: str | None, label: str) -> None:
    """Reject anything whose bytes do not match its declared image type.

    The MIME type arrives as `UploadFile.content_type`, i.e. from the client,
    and the buckets these files land in are public-read — so the declared type
    is what the file is later served as. Checking the signature keeps a caller
    from parking arbitrary content under an image content type.
    """
    if not mime_type or mime_type not in IMAGE_MIME_TO_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Invalid {label} type. Supported types: PNG, JPG, JPEG.',
        )

    signatures = _IMAGE_SIGNATURES[mime_type]
    if not any(file_contents.startswith(signature) for signature in signatures):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'That {label} is not a valid PNG or JPEG image.',
        )
