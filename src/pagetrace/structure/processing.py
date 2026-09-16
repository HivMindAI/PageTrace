"""Orchestration for provenance-aware structured document representation."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pagetrace.documents import (
    DimensionUnit,
    DocumentManifest,
    MediaType,
    PageManifest,
    load_document,
)
from pagetrace.extraction import load_text_extraction
from pagetrace.extraction.source import read_verified_source
from pagetrace.ocr import OcrArtifact, OcrPageResult, OcrPageStatus, load_ocr_artifact
from pagetrace.ocr.engine import (
    OcrEngineResult,
    create_ocr_engine,
    current_ocr_processor_descriptor,
)
from pagetrace.ocr.rendering import RenderedPage, render_selected_pages
from pagetrace.structure.errors import (
    StructureDependencyError,
    StructureLimitError,
    StructureProcessingError,
)
from pagetrace.structure.layout import (
    PdfPageLayout,
    current_structure_processor_descriptor,
    extract_pdf_layout,
)
from pagetrace.structure.models import (
    DEFAULT_STRUCTURE_CONFIG,
    STRUCTURE_SCHEMA_VERSION,
    BoundingBox,
    CoordinateOrigin,
    StructureConfig,
    StructuredDocumentArtifact,
    StructuredPage,
    StructuredTable,
    TextSpan,
    TextSpanSource,
    span_id_for,
    structure_artifact_id_for,
    structure_content_fingerprint_for,
    table_id_for,
)
from pagetrace.structure.storage import persist_structured_document


def structure_document(
    document_id: str,
    source_text_artifact_id: str,
    source_ocr_artifact_id: str,
    *,
    store: Path,
    configuration: StructureConfig = DEFAULT_STRUCTURE_CONFIG,
) -> StructuredDocumentArtifact:
    """Create and persist positioned page structure from verified prior-stage artifacts."""

    normalized_store = Path(store)
    manifest = load_document(document_id, store=normalized_store)
    text_artifact = load_text_extraction(
        source_text_artifact_id,
        document_id=document_id,
        store=normalized_store,
    )
    ocr_artifact = load_ocr_artifact(
        source_ocr_artifact_id,
        document_id=document_id,
        store=normalized_store,
    )
    if ocr_artifact.source_text_artifact_id != text_artifact.artifact_id:
        raise StructureProcessingError(
            "OCR artifact does not derive from the selected text-routing artifact"
        )
    source_bytes = read_verified_source(manifest, store=normalized_store)
    processor = current_structure_processor_descriptor(manifest.media_type)
    pdf_layout = (
        extract_pdf_layout(source_bytes, manifest, configuration)
        if manifest.media_type is MediaType.PDF
        else ()
    )
    ocr_spans = _replay_ocr_geometry(
        source_bytes,
        manifest,
        ocr_artifact,
        configuration,
    )

    pages: list[StructuredPage] = []
    document_span_count = 0
    for index, (manifest_page, text_page, _ocr_page) in enumerate(
        zip(manifest.pages, text_artifact.pages, ocr_artifact.pages, strict=True)
    ):
        layout_page = pdf_layout[index] if pdf_layout else None
        width, height = _page_dimensions(manifest_page, layout_page)
        raw_spans: list[tuple[TextSpanSource, str, BoundingBox, float | None]] = []
        if layout_page is not None and text_page.text is not None:
            if text_page.non_whitespace_character_count and not layout_page.words:
                raise StructureProcessingError(
                    "pdfplumber returned no positioned words for embedded-text page "
                    f"{text_page.page_number}"
                )
            raw_spans.extend(
                (
                    TextSpanSource.EMBEDDED_WORD,
                    word.text,
                    word.bounding_box,
                    None,
                )
                for word in layout_page.words
            )
        raw_spans.extend(ocr_spans.get(manifest_page.page_number, ()))
        if len(raw_spans) > configuration.limits.max_spans_per_page:
            raise StructureLimitError(
                f"page {manifest_page.page_number} exceeds the structured span limit"
            )
        document_span_count += len(raw_spans)
        if document_span_count > configuration.limits.max_spans_per_document:
            raise StructureLimitError("document exceeds the structured span limit")

        spans = tuple(
            TextSpan(
                span_id=span_id_for(manifest_page.page_id, source, span_index),
                span_index=span_index,
                source=source,
                text=text,
                bounding_box=box,
                confidence=confidence,
            )
            for span_index, (source, text, box, confidence) in enumerate(raw_spans, start=1)
        )
        tables = _tables(manifest_page.page_id, layout_page)
        pages.append(
            StructuredPage(
                page_id=manifest_page.page_id,
                page_number=manifest_page.page_number,
                width=width,
                height=height,
                dimension_unit=manifest_page.dimension_unit,
                coordinate_origin=CoordinateOrigin.TOP_LEFT,
                source_rotation_degrees=manifest_page.rotation_degrees,
                spans=spans,
                tables=tables,
            )
        )

    immutable_pages = tuple(pages)
    span_count = sum(len(page.spans) for page in immutable_pages)
    table_count = sum(len(page.tables) for page in immutable_pages)
    cell_count = sum(len(table.cells) for page in immutable_pages for table in page.tables)
    artifact = StructuredDocumentArtifact(
        schema_version=STRUCTURE_SCHEMA_VERSION,
        artifact_id=structure_artifact_id_for(
            manifest.fingerprint,
            text_artifact.artifact_id,
            text_artifact.content_fingerprint,
            ocr_artifact.artifact_id,
            ocr_artifact.content_fingerprint,
            processor,
            configuration,
        ),
        document_id=manifest.document_id,
        document_fingerprint=manifest.fingerprint,
        source_text_artifact_id=text_artifact.artifact_id,
        source_text_content_fingerprint=text_artifact.content_fingerprint,
        source_ocr_artifact_id=ocr_artifact.artifact_id,
        source_ocr_content_fingerprint=ocr_artifact.content_fingerprint,
        processor=processor,
        configuration=configuration,
        page_count=len(immutable_pages),
        span_count=span_count,
        table_count=table_count,
        cell_count=cell_count,
        content_fingerprint=structure_content_fingerprint_for(immutable_pages),
        pages=immutable_pages,
    )
    return persist_structured_document(artifact, store=normalized_store)


def _replay_ocr_geometry(
    source_bytes: bytes,
    manifest: DocumentManifest,
    artifact: OcrArtifact,
    configuration: StructureConfig,
) -> dict[int, tuple[tuple[TextSpanSource, str, BoundingBox, float], ...]]:
    selected = tuple(
        page.page_number for page in artifact.pages if page.status is not OcrPageStatus.NOT_SELECTED
    )
    if not selected:
        return {}
    current_processor = current_ocr_processor_descriptor(manifest.media_type)
    if current_processor != artifact.processor:
        raise StructureDependencyError(
            "installed OCR engine, models, or renderer do not match the source OCR artifact"
        )
    engine = create_ocr_engine(artifact.configuration)
    rendered_pages: Iterator[RenderedPage] = iter(
        render_selected_pages(
            source_bytes,
            manifest,
            selected,
            artifact.configuration,
        )
    )
    result: dict[int, tuple[tuple[TextSpanSource, str, BoundingBox, float], ...]] = {}
    for source_page in artifact.pages:
        if source_page.status is OcrPageStatus.NOT_SELECTED:
            continue
        try:
            rendered = next(rendered_pages)
        except StopIteration as exc:
            raise StructureProcessingError("renderer omitted a selected OCR page") from exc
        if rendered.page_number != source_page.page_number:
            raise StructureProcessingError("renderer returned OCR pages out of order")
        if (
            rendered.width != source_page.rendered_width_pixels
            or rendered.height != source_page.rendered_height_pixels
        ):
            raise StructureProcessingError(
                f"OCR replay dimensions do not match source artifact page {source_page.page_number}"
            )
        replay = engine.recognize(rendered.image)
        _validate_ocr_replay(replay, source_page)
        display_page = manifest.pages[source_page.page_number - 1]
        width, height = _page_dimensions(display_page, None)
        spans: list[tuple[TextSpanSource, str, BoundingBox, float]] = []
        for text, confidence, quadrilateral in zip(
            replay.lines, replay.confidences, replay.boxes, strict=True
        ):
            xs = tuple(point[0] for point in quadrilateral)
            ys = tuple(point[1] for point in quadrilateral)
            try:
                box = BoundingBox(
                    _round(min(xs) * width / rendered.width, configuration),
                    _round(min(ys) * height / rendered.height, configuration),
                    _round(max(xs) * width / rendered.width, configuration),
                    _round(max(ys) * height / rendered.height, configuration),
                )
            except ValueError as exc:
                raise StructureProcessingError(
                    f"OCR geometry is invalid for source artifact page {source_page.page_number}"
                ) from exc
            spans.append((TextSpanSource.OCR_LINE, text, box, confidence))
        result[source_page.page_number] = tuple(spans)
    try:
        next(rendered_pages)
    except StopIteration:
        return result
    raise StructureProcessingError("renderer returned an unselected OCR page")


def _validate_ocr_replay(result: OcrEngineResult, source_page: OcrPageResult) -> None:
    if len(result.lines) != len(result.confidences) or len(result.lines) != len(result.boxes):
        raise StructureProcessingError("OCR replay returned incomplete positioned output")
    text = "\n".join(result.lines) if result.lines else None
    mean_confidence = (
        round(sum(result.confidences) / len(result.confidences), 6) if result.confidences else None
    )
    if (
        text != source_page.text
        or len(result.lines) != source_page.line_count
        or mean_confidence != source_page.mean_confidence
    ):
        raise StructureProcessingError(
            f"OCR replay does not match source artifact page {source_page.page_number}"
        )


def _page_dimensions(page: PageManifest, layout: PdfPageLayout | None) -> tuple[float, float]:
    if layout is not None:
        return layout.width, layout.height
    width = float(page.width)
    height = float(page.height)
    if page.dimension_unit is DimensionUnit.POINTS and page.rotation_degrees in (90, 270):
        width, height = height, width
    return width, height


def _tables(page_id: str, layout: PdfPageLayout | None) -> tuple[StructuredTable, ...]:
    if layout is None:
        return ()
    return tuple(
        StructuredTable(
            table_id=table_id_for(page_id, table_index),
            table_index=table_index,
            bounding_box=table.bounding_box,
            row_count=table.row_count,
            column_count=table.column_count,
            cells=table.cells,
        )
        for table_index, table in enumerate(layout.tables, start=1)
    )


def _round(value: float, configuration: StructureConfig) -> float:
    result = round(value, configuration.coordinate_precision)
    return 0.0 if result == 0 else result
