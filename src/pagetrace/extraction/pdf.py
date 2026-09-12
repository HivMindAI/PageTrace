"""Page-level embedded PDF text extraction using the declared pypdf backend."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from pagetrace.documents.models import DocumentManifest
from pagetrace.extraction.errors import ExtractionLimitError, ExtractionProcessingError
from pagetrace.extraction.models import (
    ExtractionMethod,
    PageTextResult,
    PageTextStatus,
    TextExtractionConfig,
)

_PARSER_FAILURES = (PdfReadError, KeyError, TypeError, ValueError)


def extract_pdf_page_results(
    source_bytes: bytes,
    manifest: DocumentManifest,
    configuration: TextExtractionConfig,
) -> tuple[PageTextResult, ...]:
    """Extract faithful embedded text or explicitly route each PDF page."""

    try:
        reader = PdfReader(BytesIO(source_bytes), strict=True)
        if reader.is_encrypted:
            raise ExtractionProcessingError("verified PDF unexpectedly became encrypted")
        if len(reader.pages) != manifest.page_count:
            raise ExtractionProcessingError(
                "PDF page count no longer matches the verified document manifest"
            )
    except ExtractionProcessingError:
        raise
    except _PARSER_FAILURES as exc:
        raise ExtractionProcessingError(
            "pypdf could not initialize embedded-text extraction"
        ) from exc

    results: list[PageTextResult] = []
    document_character_count = 0
    for page_manifest, page in zip(manifest.pages, reader.pages, strict=True):
        try:
            extracted = page.extract_text(extraction_mode=configuration.pdf_extraction_mode.value)
        except _PARSER_FAILURES as exc:
            raise ExtractionProcessingError(
                f"pypdf embedded-text extraction failed on page {page_manifest.page_number}"
            ) from exc
        if not isinstance(extracted, str):
            raise ExtractionProcessingError(
                f"pypdf returned an invalid text value on page {page_manifest.page_number}"
            )
        character_count = len(extracted)
        if character_count > configuration.limits.max_characters_per_page:
            raise ExtractionLimitError(
                f"page {page_manifest.page_number} extracted text exceeds the "
                f"{configuration.limits.max_characters_per_page}-character per-page limit"
            )
        document_character_count += character_count
        if document_character_count > configuration.limits.max_characters_per_document:
            raise ExtractionLimitError(
                "document extracted text exceeds the "
                f"{configuration.limits.max_characters_per_document}-character total limit "
                f"at page {page_manifest.page_number}"
            )
        results.append(
            _route_extracted_text(
                page_manifest.page_id, page_manifest.page_number, extracted, configuration
            )
        )
    return tuple(results)


def _route_extracted_text(
    page_id: str,
    page_number: int,
    extracted: str,
    configuration: TextExtractionConfig,
) -> PageTextResult:
    non_whitespace_count = sum(not character.isspace() for character in extracted)
    if non_whitespace_count == 0:
        return PageTextResult(
            page_id=page_id,
            page_number=page_number,
            method=ExtractionMethod.PYPDF_EMBEDDED_TEXT,
            status=PageTextStatus.OCR_CANDIDATE,
            text=None,
            character_count=0,
            non_whitespace_character_count=0,
        )

    status = (
        PageTextStatus.EMBEDDED_TEXT
        if non_whitespace_count >= configuration.minimum_embedded_characters
        else PageTextStatus.SPARSE_EMBEDDED_TEXT
    )
    return PageTextResult(
        page_id=page_id,
        page_number=page_number,
        method=ExtractionMethod.PYPDF_EMBEDDED_TEXT,
        status=status,
        text=extracted,
        character_count=len(extracted),
        non_whitespace_character_count=non_whitespace_count,
    )
