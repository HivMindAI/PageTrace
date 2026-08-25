"""Parser-level validation and deterministic manifest construction."""

from __future__ import annotations

import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from pagetrace.documents.errors import (
    DocumentLimitError,
    EncryptedDocumentError,
    InvalidDocumentError,
    UnsupportedDocumentError,
)
from pagetrace.documents.models import (
    SCHEMA_VERSION,
    SHA256_ALGORITHM,
    DimensionUnit,
    DocumentManifest,
    DocumentMetadata,
    IngestionLimits,
    MediaType,
    PageManifest,
    page_id_for,
)

_PDF_METADATA_KEYS = {
    "title": "/Title",
    "author": "/Author",
    "subject": "/Subject",
    "creator": "/Creator",
    "producer": "/Producer",
    "creation_date": "/CreationDate",
    "modification_date": "/ModDate",
}


def validate_staged_document(
    staged_path: Path,
    media_type: MediaType,
    *,
    document_id: str,
    fingerprint: str,
    byte_size: int,
    limits: IngestionLimits,
) -> DocumentManifest:
    """Validate staged bytes and construct their canonical immutable manifest."""

    if media_type is MediaType.PDF:
        pages, metadata = _validate_pdf(staged_path, document_id, limits)
    else:
        pages, metadata = _validate_image(staged_path, media_type, document_id, limits)

    return DocumentManifest(
        schema_version=SCHEMA_VERSION,
        document_id=document_id,
        fingerprint_algorithm=SHA256_ALGORITHM,
        fingerprint=fingerprint,
        media_type=media_type,
        byte_size=byte_size,
        page_count=len(pages),
        document_metadata=metadata,
        pages=pages,
    )


def _validate_pdf(
    path: Path, document_id: str, limits: IngestionLimits
) -> tuple[tuple[PageManifest, ...], DocumentMetadata]:
    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise EncryptedDocumentError("encrypted PDF documents are not supported")

        pages: list[PageManifest] = []
        for page_number, page in enumerate(reader.pages, start=1):
            if page_number > limits.max_pdf_pages:
                raise DocumentLimitError(
                    f"PDF exceeds the {limits.max_pdf_pages}-page ingestion limit"
                )
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            rotation = int(page.rotation or 0) % 360
            pages.append(
                PageManifest(
                    page_id=page_id_for(document_id, page_number),
                    page_number=page_number,
                    width=width,
                    height=height,
                    dimension_unit=DimensionUnit.POINTS,
                    rotation_degrees=rotation,
                )
            )
        if not pages:
            raise InvalidDocumentError("PDF must contain at least one page")
        metadata = _pdf_metadata(reader)
    except (EncryptedDocumentError, DocumentLimitError, InvalidDocumentError):
        raise
    except (PdfReadError, OSError, TypeError, ValueError) as exc:
        raise InvalidDocumentError("PDF parser rejected the staged document") from exc
    return tuple(pages), metadata


def _pdf_metadata(reader: PdfReader) -> DocumentMetadata:
    raw = reader.metadata
    if raw is None:
        return DocumentMetadata()
    values: dict[str, str | None] = {}
    for field, key in _PDF_METADATA_KEYS.items():
        value = raw.get(key)
        values[field] = value if isinstance(value, str) else None
    return DocumentMetadata(**values)


def _validate_image(
    path: Path, media_type: MediaType, document_id: str, limits: IngestionLimits
) -> tuple[tuple[PageManifest, ...], DocumentMetadata]:
    expected_format = "PNG" if media_type is MediaType.PNG else "JPEG"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format != expected_format:
                    raise InvalidDocumentError(
                        f"image parser identified {image.format!r}, expected {expected_format}"
                    )
                width, height = image.size
                if width * height > limits.max_image_pixels:
                    raise DocumentLimitError(
                        f"image exceeds the {limits.max_image_pixels}-pixel ingestion limit"
                    )
                if getattr(image, "n_frames", 1) != 1:
                    raise UnsupportedDocumentError("multi-frame images are not supported")
                image.verify()
    except (DocumentLimitError, InvalidDocumentError, UnsupportedDocumentError):
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise DocumentLimitError("image exceeds Pillow's decompression-bomb limit") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidDocumentError("image parser rejected the staged document") from exc

    page = PageManifest(
        page_id=page_id_for(document_id, 1),
        page_number=1,
        width=width,
        height=height,
        dimension_unit=DimensionUnit.PIXELS,
        rotation_degrees=None,
    )
    return (page,), DocumentMetadata()
