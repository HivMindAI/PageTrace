"""Orchestration for extraction from verified PageTrace document artifacts."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

from pagetrace.documents import MediaType, load_document
from pagetrace.extraction.errors import ExtractionUnsupportedError
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
from pagetrace.extraction.source import read_verified_source
from pagetrace.extraction.storage import persist_text_extraction


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
        source_bytes = read_verified_source(manifest, store=Path(store))
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
