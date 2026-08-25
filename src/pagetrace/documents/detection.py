"""Content-signature detection for supported document formats."""

from pathlib import Path

from pagetrace.documents.errors import DocumentStorageError, UnsupportedDocumentError
from pagetrace.documents.models import MediaType

_PDF_SIGNATURE = b"%PDF-"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"


def detect_media_type(staged_path: Path) -> MediaType:
    """Detect a supported media type from staged file bytes, never its name."""

    try:
        with staged_path.open("rb") as stream:
            signature = stream.read(8)
    except OSError as exc:
        raise DocumentStorageError("could not read staged document bytes") from exc

    if signature.startswith(_PDF_SIGNATURE):
        return MediaType.PDF
    if signature.startswith(_PNG_SIGNATURE):
        return MediaType.PNG
    if signature.startswith(_JPEG_SIGNATURE):
        return MediaType.JPEG
    raise UnsupportedDocumentError("supported document content must be PDF, PNG, or JPEG")
