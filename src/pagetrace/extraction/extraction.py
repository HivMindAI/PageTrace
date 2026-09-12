"""Orchestration for extraction from verified PageTrace document artifacts."""

from __future__ import annotations

import hashlib
import os
import stat
from importlib.metadata import version
from pathlib import Path

from pagetrace.documents import DocumentManifest, MediaType, load_document
from pagetrace.extraction.errors import (
    ExtractionIntegrityError,
    ExtractionUnsupportedError,
)
from pagetrace.extraction.models import (
    DEFAULT_TEXT_EXTRACTION_CONFIG,
    EXTRACTION_SCHEMA_VERSION,
    EXTRACTOR_NAME,
    EXTRACTOR_VERSION,
    PDF_BACKEND_NAME,
    ExtractionMethod,
    ExtractorDescriptor,
    PageTextResult,
    PageTextStatus,
    TextExtractionArtifact,
    TextExtractionConfig,
    artifact_id_for,
    content_fingerprint_for,
)
from pagetrace.extraction.pdf import extract_pdf_page_results
from pagetrace.extraction.storage import persist_text_extraction

_HASH_CHUNK_SIZE = 1024 * 1024
_SOURCE_NAMES = {
    MediaType.PDF: "source.pdf",
    MediaType.PNG: "source.png",
    MediaType.JPEG: "source.jpg",
}


def extract_document_text(
    document_id: str,
    *,
    store: Path,
    configuration: TextExtractionConfig = DEFAULT_TEXT_EXTRACTION_CONFIG,
) -> TextExtractionArtifact:
    """Extract embedded text from one verified stored document and persist the result."""

    manifest = load_document(document_id, store=Path(store))
    extractor = current_extractor_descriptor()
    if manifest.media_type is MediaType.PDF:
        source_bytes = _read_verified_source(manifest, store=Path(store))
        pages = extract_pdf_page_results(source_bytes, manifest, configuration)
    elif manifest.media_type in (MediaType.PNG, MediaType.JPEG):
        pages = tuple(
            _image_ocr_candidate(page.page_id, page.page_number) for page in manifest.pages
        )
    else:
        raise ExtractionUnsupportedError(
            f"stored media type is not supported for text routing: {manifest.media_type.value}"
        )

    artifact = TextExtractionArtifact(
        schema_version=EXTRACTION_SCHEMA_VERSION,
        artifact_id=artifact_id_for(manifest.fingerprint, extractor, configuration),
        document_id=manifest.document_id,
        document_fingerprint=manifest.fingerprint,
        extractor=extractor,
        configuration=configuration,
        page_count=len(pages),
        content_fingerprint=content_fingerprint_for(pages),
        pages=pages,
    )
    return persist_text_extraction(artifact, store=Path(store))


def current_extractor_descriptor() -> ExtractorDescriptor:
    """Return real version provenance for this stage and its installed PDF backend."""

    return ExtractorDescriptor(
        name=EXTRACTOR_NAME,
        version=EXTRACTOR_VERSION,
        pdf_backend_name=PDF_BACKEND_NAME,
        pdf_backend_version=version(PDF_BACKEND_NAME),
    )


def _image_ocr_candidate(page_id: str, page_number: int) -> PageTextResult:
    return PageTextResult(
        page_id=page_id,
        page_number=page_number,
        method=ExtractionMethod.OCR_ROUTING_ONLY,
        status=PageTextStatus.OCR_CANDIDATE,
        text=None,
        character_count=0,
        non_whitespace_character_count=0,
    )


def _read_verified_source(manifest: DocumentManifest, *, store: Path) -> bytes:
    source_path = (
        store.expanduser().resolve()
        / "documents"
        / manifest.document_id
        / _SOURCE_NAMES[manifest.media_type]
    )
    try:
        initial = source_path.lstat()
    except OSError as exc:
        raise ExtractionIntegrityError(
            "verified source could not be inspected for extraction"
        ) from exc
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
        raise ExtractionIntegrityError("verified source is no longer a safe regular file")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source_path, flags)
    except OSError as exc:
        raise ExtractionIntegrityError("verified source could not be opened safely") from exc

    digest = hashlib.sha256()
    source = bytearray()
    try:
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev != initial.st_dev or opened.st_ino != initial.st_ino
            ):
                raise ExtractionIntegrityError("verified source changed while it was being opened")
            while chunk := stream.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
                source.extend(chunk)
            after = os.fstat(stream.fileno())
    except ExtractionIntegrityError:
        raise
    except OSError as exc:
        raise ExtractionIntegrityError("verified source could not be read for extraction") from exc

    if opened.st_size != after.st_size or len(source) != manifest.byte_size:
        raise ExtractionIntegrityError("verified source size changed before extraction")
    if digest.hexdigest() != manifest.fingerprint:
        raise ExtractionIntegrityError("verified source fingerprint changed before extraction")
    return bytes(source)
