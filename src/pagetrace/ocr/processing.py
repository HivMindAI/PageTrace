"""Orchestration for OCR of pages selected by a verified text-routing artifact."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pagetrace.documents import load_document
from pagetrace.extraction import load_text_extraction
from pagetrace.extraction.models import PageTextResult, PageTextStatus
from pagetrace.extraction.source import read_verified_source
from pagetrace.ocr.engine import (
    OcrEngine,
    OcrEngineResult,
    create_ocr_engine,
    current_ocr_processor_descriptor,
)
from pagetrace.ocr.errors import OcrLimitError, OcrProcessingError
from pagetrace.ocr.models import (
    DEFAULT_OCR_CONFIG,
    OCR_SCHEMA_VERSION,
    OcrArtifact,
    OcrConfig,
    OcrMethod,
    OcrPageResult,
    OcrPageStatus,
    OcrRoutingPolicy,
    ocr_artifact_id_for,
    ocr_content_fingerprint_for,
)
from pagetrace.ocr.rendering import RenderedPage, render_selected_pages
from pagetrace.ocr.storage import persist_ocr_artifact


def ocr_document(
    document_id: str,
    source_text_artifact_id: str,
    *,
    store: Path,
    configuration: OcrConfig = DEFAULT_OCR_CONFIG,
) -> OcrArtifact:
    """OCR only pages selected by verified Milestone 2A routing and persist the result."""

    normalized_store = Path(store)
    manifest = load_document(document_id, store=normalized_store)
    source_artifact = load_text_extraction(
        source_text_artifact_id,
        document_id=document_id,
        store=normalized_store,
    )
    selected_page_numbers = tuple(
        page.page_number
        for page in source_artifact.pages
        if _should_select(page.status, configuration.routing_policy)
    )
    if len(selected_page_numbers) > configuration.limits.max_pages_per_document:
        raise OcrLimitError(
            "OCR selection exceeds the "
            f"{configuration.limits.max_pages_per_document}-page document limit"
        )

    processor = current_ocr_processor_descriptor(manifest.media_type)
    engine: OcrEngine | None = None
    rendered_page_iterator: Iterator[RenderedPage] = iter(())
    if selected_page_numbers:
        source_bytes = read_verified_source(manifest, store=normalized_store)
        engine = create_ocr_engine(configuration)
        rendered_page_iterator = iter(
            render_selected_pages(
                source_bytes,
                manifest,
                selected_page_numbers,
                configuration,
            )
        )

    pages: list[OcrPageResult] = []
    document_character_count = 0
    for source_page in source_artifact.pages:
        if source_page.page_number not in selected_page_numbers:
            pages.append(_not_selected_page(source_page))
            continue
        if engine is None:
            raise OcrProcessingError("OCR engine was not initialized for a selected page")
        try:
            rendered_page = next(rendered_page_iterator)
        except StopIteration as exc:
            raise OcrProcessingError("renderer omitted a selected OCR page") from exc
        if rendered_page.page_number != source_page.page_number:
            raise OcrProcessingError("renderer returned selected OCR pages out of order")
        page, document_character_count = _recognize_page(
            source_page,
            rendered_page,
            engine,
            configuration,
            document_character_count,
        )
        pages.append(page)
    try:
        next(rendered_page_iterator)
    except StopIteration:
        pass
    else:
        raise OcrProcessingError("renderer returned an unselected OCR page")

    immutable_pages = tuple(pages)
    artifact = OcrArtifact(
        schema_version=OCR_SCHEMA_VERSION,
        artifact_id=ocr_artifact_id_for(
            manifest.fingerprint,
            source_artifact.artifact_id,
            source_artifact.content_fingerprint,
            processor,
            configuration,
        ),
        document_id=manifest.document_id,
        document_fingerprint=manifest.fingerprint,
        source_text_artifact_id=source_artifact.artifact_id,
        source_text_content_fingerprint=source_artifact.content_fingerprint,
        processor=processor,
        configuration=configuration,
        page_count=len(immutable_pages),
        selected_page_count=len(selected_page_numbers),
        content_fingerprint=ocr_content_fingerprint_for(immutable_pages),
        pages=immutable_pages,
    )
    return persist_ocr_artifact(artifact, store=normalized_store)


def _should_select(status: PageTextStatus, routing_policy: OcrRoutingPolicy) -> bool:
    return status is PageTextStatus.OCR_CANDIDATE or (
        status is PageTextStatus.SPARSE_EMBEDDED_TEXT
        and routing_policy is OcrRoutingPolicy.CANDIDATES_AND_SPARSE
    )


def _not_selected_page(source_page: PageTextResult) -> OcrPageResult:
    return OcrPageResult(
        page_id=source_page.page_id,
        page_number=source_page.page_number,
        source_status=source_page.status,
        method=OcrMethod.NOT_APPLIED,
        status=OcrPageStatus.NOT_SELECTED,
        text=None,
        character_count=0,
        non_whitespace_character_count=0,
        line_count=0,
        mean_confidence=None,
        rendered_width_pixels=None,
        rendered_height_pixels=None,
    )


def _recognize_page(
    source_page: PageTextResult,
    rendered: RenderedPage,
    engine: OcrEngine,
    configuration: OcrConfig,
    previous_document_character_count: int,
) -> tuple[OcrPageResult, int]:
    backend_result = engine.recognize(rendered.image)
    _validate_backend_result(backend_result, source_page.page_number, configuration)
    character_count = sum(len(line) for line in backend_result.lines) + max(
        0, len(backend_result.lines) - 1
    )
    if character_count > configuration.limits.max_characters_per_page:
        raise OcrLimitError(
            f"page {source_page.page_number} OCR text exceeds the "
            f"{configuration.limits.max_characters_per_page}-character per-page limit"
        )
    document_character_count = previous_document_character_count + character_count
    if document_character_count > configuration.limits.max_characters_per_document:
        raise OcrLimitError(
            "document OCR text exceeds the "
            f"{configuration.limits.max_characters_per_document}-character total limit "
            f"at page {source_page.page_number}"
        )

    if not backend_result.lines:
        return (
            OcrPageResult(
                page_id=source_page.page_id,
                page_number=source_page.page_number,
                source_status=source_page.status,
                method=OcrMethod.RAPIDOCR,
                status=OcrPageStatus.OCR_NO_TEXT,
                text=None,
                character_count=0,
                non_whitespace_character_count=0,
                line_count=0,
                mean_confidence=None,
                rendered_width_pixels=rendered.width,
                rendered_height_pixels=rendered.height,
            ),
            document_character_count,
        )

    text = "\n".join(backend_result.lines)
    mean_confidence = round(sum(backend_result.confidences) / len(backend_result.confidences), 6)
    return (
        OcrPageResult(
            page_id=source_page.page_id,
            page_number=source_page.page_number,
            source_status=source_page.status,
            method=OcrMethod.RAPIDOCR,
            status=OcrPageStatus.OCR_TEXT,
            text=text,
            character_count=len(text),
            non_whitespace_character_count=sum(not character.isspace() for character in text),
            line_count=len(backend_result.lines),
            mean_confidence=mean_confidence,
            rendered_width_pixels=rendered.width,
            rendered_height_pixels=rendered.height,
        ),
        document_character_count,
    )


def _validate_backend_result(
    result: OcrEngineResult, page_number: int, configuration: OcrConfig
) -> None:
    if len(result.lines) != len(result.confidences):
        raise OcrProcessingError(f"OCR backend returned mismatched output on page {page_number}")
    if len(result.lines) > configuration.limits.max_lines_per_page:
        raise OcrLimitError(
            f"page {page_number} OCR output exceeds the "
            f"{configuration.limits.max_lines_per_page}-line limit"
        )
    if any(confidence < configuration.minimum_confidence for confidence in result.confidences):
        raise OcrProcessingError(
            f"OCR backend returned output below the confidence policy on page {page_number}"
        )
