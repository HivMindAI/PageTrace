"""Immutable models for provenance-aware structured document representation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum

from pagetrace.documents import DimensionUnit
from pagetrace.documents.models import document_id_for, is_sha256, page_id_for
from pagetrace.extraction.models import is_extraction_id
from pagetrace.ocr.models import is_ocr_artifact_id

STRUCTURE_SCHEMA_VERSION = 1
STRUCTURE_PROCESSOR_NAME = "pagetrace-structured-document"
STRUCTURE_PROCESSOR_VERSION = "1"
PDF_LAYOUT_BACKEND_NAME = "pdfplumber"
_STRUCTURE_ID_PATTERN = re.compile(r"^structure-sha256-[0-9a-f]{64}$")


class CoordinateOrigin(StrEnum):
    """Origin and direction used by all structured bounding boxes."""

    TOP_LEFT = "top_left"


class TextSpanSource(StrEnum):
    """Evidence-producing source for one positioned text span."""

    EMBEDDED_WORD = "embedded_word"
    OCR_LINE = "ocr_line"


class TableStrategy(StrEnum):
    """Supported deterministic pdfplumber table boundary strategies."""

    LINES = "lines"
    LINES_STRICT = "lines_strict"


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned box in a page's explicit top-left coordinate space."""

    x0: float
    top: float
    x1: float
    bottom: float

    def __post_init__(self) -> None:
        for name, value in (
            ("x0", self.x0),
            ("top", self.top),
            ("x1", self.x1),
            ("bottom", self.bottom),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be a finite coordinate")
        if self.x0 < 0 or self.top < 0 or self.x1 <= self.x0 or self.bottom <= self.top:
            raise ValueError("bounding box must have positive area in non-negative coordinates")

    def within(self, width: float, height: float) -> bool:
        """Return whether the box is fully inside the given page or container bounds."""

        return self.x1 <= width and self.bottom <= height

    def within_box(self, container: BoundingBox) -> bool:
        """Return whether the box is fully inside another box."""

        return (
            self.x0 >= container.x0
            and self.top >= container.top
            and self.x1 <= container.x1
            and self.bottom <= container.bottom
        )


@dataclass(frozen=True, slots=True)
class StructureLimits:
    """Bounds for positioned words, OCR lines, tables, and cells."""

    max_spans_per_page: int = 100_000
    max_spans_per_document: int = 1_000_000
    max_tables_per_page: int = 100
    max_tables_per_document: int = 1_000
    max_cells_per_table: int = 10_000
    max_cells_per_document: int = 100_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_spans_per_page", self.max_spans_per_page),
            ("max_spans_per_document", self.max_spans_per_document),
            ("max_tables_per_page", self.max_tables_per_page),
            ("max_tables_per_document", self.max_tables_per_document),
            ("max_cells_per_table", self.max_cells_per_table),
            ("max_cells_per_document", self.max_cells_per_document),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_STRUCTURE_LIMITS = StructureLimits()


@dataclass(frozen=True, slots=True)
class StructureConfig:
    """Output-affecting word grouping, table detection, precision, and limits."""

    coordinate_precision: int = 6
    word_x_tolerance: float = 3.0
    word_y_tolerance: float = 3.0
    table_vertical_strategy: TableStrategy = TableStrategy.LINES
    table_horizontal_strategy: TableStrategy = TableStrategy.LINES
    limits: StructureLimits = DEFAULT_STRUCTURE_LIMITS

    def __post_init__(self) -> None:
        if (
            isinstance(self.coordinate_precision, bool)
            or not isinstance(self.coordinate_precision, int)
            or not 0 <= self.coordinate_precision <= 9
        ):
            raise ValueError("coordinate_precision must be an integer from 0 to 9")
        for name, value in (
            ("word_x_tolerance", self.word_x_tolerance),
            ("word_y_tolerance", self.word_y_tolerance),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} must be a finite non-negative number")
        if not isinstance(self.table_vertical_strategy, TableStrategy) or not isinstance(
            self.table_horizontal_strategy, TableStrategy
        ):
            raise ValueError("table strategies must be supported line strategies")
        if not isinstance(self.limits, StructureLimits):
            raise ValueError("limits must be a StructureLimits value")


DEFAULT_STRUCTURE_CONFIG = StructureConfig()


@dataclass(frozen=True, slots=True)
class StructureProcessorDescriptor:
    """Versioned identity of this stage and its optional PDF layout backend."""

    name: str
    version: str
    pdf_layout_backend_name: str | None
    pdf_layout_backend_version: str | None

    def __post_init__(self) -> None:
        if self.name != STRUCTURE_PROCESSOR_NAME:
            raise ValueError(f"structure processor name must be {STRUCTURE_PROCESSOR_NAME}")
        if not self.version:
            raise ValueError("structure processor version must not be empty")
        if (self.pdf_layout_backend_name is None) != (self.pdf_layout_backend_version is None):
            raise ValueError("PDF layout backend name and version must both be present or absent")
        if (
            self.pdf_layout_backend_name is not None
            and self.pdf_layout_backend_name != PDF_LAYOUT_BACKEND_NAME
        ):
            raise ValueError(f"PDF layout backend name must be {PDF_LAYOUT_BACKEND_NAME}")
        if self.pdf_layout_backend_version == "":
            raise ValueError("PDF layout backend version must not be empty")


@dataclass(frozen=True, slots=True)
class TextSpan:
    """Positioned embedded word or OCR line with stable source-local order."""

    span_id: str
    span_index: int
    source: TextSpanSource
    text: str
    bounding_box: BoundingBox
    confidence: float | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.span_index, bool)
            or not isinstance(self.span_index, int)
            or self.span_index < 1
        ):
            raise ValueError("span_index must be a positive 1-based integer")
        if not isinstance(self.source, TextSpanSource):
            raise ValueError("source must be a supported text span source")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text spans must contain non-whitespace text")
        if not isinstance(self.bounding_box, BoundingBox):
            raise ValueError("bounding_box must be a BoundingBox")
        if self.source is TextSpanSource.EMBEDDED_WORD:
            if self.confidence is not None:
                raise ValueError("embedded words must not claim OCR confidence")
        elif (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("OCR lines must record finite confidence from 0 to 1")


@dataclass(frozen=True, slots=True)
class TableCell:
    """One detected table cell and its 1-based grid position."""

    row_index: int
    column_index: int
    bounding_box: BoundingBox
    text: str | None

    def __post_init__(self) -> None:
        for name, value in (("row_index", self.row_index), ("column_index", self.column_index)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive 1-based integer")
        if not isinstance(self.bounding_box, BoundingBox):
            raise ValueError("bounding_box must be a BoundingBox")
        if self.text is not None and (not isinstance(self.text, str) or not self.text.strip()):
            raise ValueError("table cell text must be null or non-whitespace text")


@dataclass(frozen=True, slots=True)
class StructuredTable:
    """Detected table bounds, grid shape, and positioned non-merged cells."""

    table_id: str
    table_index: int
    bounding_box: BoundingBox
    row_count: int
    column_count: int
    cells: tuple[TableCell, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("table_index", self.table_index),
            ("row_count", self.row_count),
            ("column_count", self.column_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive 1-based integer")
        if not isinstance(self.bounding_box, BoundingBox):
            raise ValueError("bounding_box must be a BoundingBox")
        if not isinstance(self.cells, tuple):
            raise ValueError("cells must be an immutable tuple")
        positions: set[tuple[int, int]] = set()
        for cell in self.cells:
            position = (cell.row_index, cell.column_index)
            if position in positions:
                raise ValueError("table cells must have unique grid positions")
            positions.add(position)
            if cell.row_index > self.row_count or cell.column_index > self.column_count:
                raise ValueError("table cell position exceeds the declared grid")
            if not cell.bounding_box.within_box(self.bounding_box):
                raise ValueError("table cell bounding box must be inside the table")


@dataclass(frozen=True, slots=True)
class StructuredPage:
    """One display-oriented page with positioned text spans and tables."""

    page_id: str
    page_number: int
    width: float
    height: float
    dimension_unit: DimensionUnit
    coordinate_origin: CoordinateOrigin
    source_rotation_degrees: int | None
    spans: tuple[TextSpan, ...]
    tables: tuple[StructuredTable, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.page_number, bool)
            or not isinstance(self.page_number, int)
            or self.page_number < 1
        ):
            raise ValueError("page_number must be a positive 1-based integer")
        for name, value in (("width", self.width), ("height", self.height)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive finite number")
        if not isinstance(self.dimension_unit, DimensionUnit):
            raise ValueError("dimension_unit must be points or pixels")
        if self.coordinate_origin is not CoordinateOrigin.TOP_LEFT:
            raise ValueError("coordinate_origin must be top_left")
        if self.source_rotation_degrees not in (None, 0, 90, 180, 270):
            raise ValueError("source_rotation_degrees is invalid")
        if not isinstance(self.spans, tuple) or not isinstance(self.tables, tuple):
            raise ValueError("spans and tables must be immutable tuples")
        for expected_index, span in enumerate(self.spans, start=1):
            if span.span_index != expected_index:
                raise ValueError("text spans must use contiguous 1-based order")
            if span.span_id != span_id_for(self.page_id, span.source, expected_index):
                raise ValueError("span_id does not match page, source, and order")
            if not span.bounding_box.within(self.width, self.height):
                raise ValueError("text span bounding box must be inside the page")
        for expected_index, table in enumerate(self.tables, start=1):
            if table.table_index != expected_index:
                raise ValueError("tables must use contiguous 1-based order")
            if table.table_id != table_id_for(self.page_id, expected_index):
                raise ValueError("table_id does not match page and order")
            if not table.bounding_box.within(self.width, self.height):
                raise ValueError("table bounding box must be inside the page")


@dataclass(frozen=True, slots=True)
class StructuredDocumentArtifact:
    """Canonical positioned representation linked to document, text, and OCR artifacts."""

    schema_version: int
    artifact_id: str
    document_id: str
    document_fingerprint: str
    source_text_artifact_id: str
    source_text_content_fingerprint: str
    source_ocr_artifact_id: str
    source_ocr_content_fingerprint: str
    processor: StructureProcessorDescriptor
    configuration: StructureConfig
    page_count: int
    span_count: int
    table_count: int
    cell_count: int
    content_fingerprint: str
    pages: tuple[StructuredPage, ...]

    def __post_init__(self) -> None:
        if self.schema_version != STRUCTURE_SCHEMA_VERSION:
            raise ValueError(f"unsupported structure schema version: {self.schema_version}")
        if not is_structure_artifact_id(self.artifact_id):
            raise ValueError("artifact_id is not a canonical structure identifier")
        if not is_sha256(self.document_fingerprint):
            raise ValueError("document_fingerprint must be a canonical SHA-256 digest")
        if self.document_id != document_id_for(self.document_fingerprint):
            raise ValueError("document_id does not match document_fingerprint")
        if not is_extraction_id(self.source_text_artifact_id):
            raise ValueError("source_text_artifact_id is not canonical")
        if not is_sha256(self.source_text_content_fingerprint):
            raise ValueError("source_text_content_fingerprint must be a SHA-256 digest")
        if not is_ocr_artifact_id(self.source_ocr_artifact_id):
            raise ValueError("source_ocr_artifact_id is not canonical")
        if not is_sha256(self.source_ocr_content_fingerprint):
            raise ValueError("source_ocr_content_fingerprint must be a SHA-256 digest")
        if self.artifact_id != structure_artifact_id_for(
            self.document_fingerprint,
            self.source_text_artifact_id,
            self.source_text_content_fingerprint,
            self.source_ocr_artifact_id,
            self.source_ocr_content_fingerprint,
            self.processor,
            self.configuration,
        ):
            raise ValueError("artifact_id does not match structure inputs")
        if not isinstance(self.pages, tuple):
            raise ValueError("pages must be an immutable tuple")
        if self.page_count != len(self.pages) or self.page_count < 1:
            raise ValueError("page_count must match a non-empty page collection")
        if not is_sha256(self.content_fingerprint):
            raise ValueError("content_fingerprint must be a canonical SHA-256 digest")
        if self.content_fingerprint != structure_content_fingerprint_for(self.pages):
            raise ValueError("content_fingerprint does not match structured pages")

        span_count = sum(len(page.spans) for page in self.pages)
        table_count = sum(len(page.tables) for page in self.pages)
        cell_count = sum(len(table.cells) for page in self.pages for table in page.tables)
        if (self.span_count, self.table_count, self.cell_count) != (
            span_count,
            table_count,
            cell_count,
        ):
            raise ValueError("artifact totals do not match structured pages")
        limits = self.configuration.limits
        if span_count > limits.max_spans_per_document:
            raise ValueError("structured document exceeds the span limit")
        if table_count > limits.max_tables_per_document:
            raise ValueError("structured document exceeds the table limit")
        if cell_count > limits.max_cells_per_document:
            raise ValueError("structured document exceeds the cell limit")
        for expected_number, page in enumerate(self.pages, start=1):
            if page.page_number != expected_number:
                raise ValueError("pages must use contiguous 1-based numbering")
            if page.page_id != page_id_for(self.document_id, expected_number):
                raise ValueError("page_id does not match document and page number")
            if len(page.spans) > limits.max_spans_per_page:
                raise ValueError("structured page exceeds the span limit")
            if len(page.tables) > limits.max_tables_per_page:
                raise ValueError("structured page exceeds the table limit")
            if any(len(table.cells) > limits.max_cells_per_table for table in page.tables):
                raise ValueError("structured table exceeds the cell limit")


def is_structure_artifact_id(value: str) -> bool:
    """Return whether *value* is a path-safe structure artifact identifier."""

    return _STRUCTURE_ID_PATTERN.fullmatch(value) is not None


def span_id_for(page_id: str, source: TextSpanSource, span_index: int) -> str:
    """Build a stable span identifier from page, evidence source, and order."""

    if isinstance(span_index, bool) or span_index < 1:
        raise ValueError("span_index must be a positive 1-based integer")
    return f"{page_id}-span-{source.value}-{span_index:06d}"


def table_id_for(page_id: str, table_index: int) -> str:
    """Build a stable table identifier from page and spatial order."""

    if isinstance(table_index, bool) or table_index < 1:
        raise ValueError("table_index must be a positive 1-based integer")
    return f"{page_id}-table-{table_index:06d}"


def structure_artifact_id_for(
    document_fingerprint: str,
    source_text_artifact_id: str,
    source_text_content_fingerprint: str,
    source_ocr_artifact_id: str,
    source_ocr_content_fingerprint: str,
    processor: StructureProcessorDescriptor,
    configuration: StructureConfig,
) -> str:
    """Derive identity from source artifacts, backend, and output-affecting policy."""

    if not is_sha256(document_fingerprint):
        raise ValueError("document_fingerprint must be a canonical SHA-256 digest")
    if not is_extraction_id(source_text_artifact_id):
        raise ValueError("source_text_artifact_id must be canonical")
    if not is_sha256(source_text_content_fingerprint):
        raise ValueError("source_text_content_fingerprint must be a SHA-256 digest")
    if not is_ocr_artifact_id(source_ocr_artifact_id):
        raise ValueError("source_ocr_artifact_id must be canonical")
    if not is_sha256(source_ocr_content_fingerprint):
        raise ValueError("source_ocr_content_fingerprint must be a SHA-256 digest")
    payload = {
        "configuration": _configuration_payload(configuration),
        "document_fingerprint": document_fingerprint,
        "processor": _processor_payload(processor),
        "schema_version": STRUCTURE_SCHEMA_VERSION,
        "source_ocr_artifact_id": source_ocr_artifact_id,
        "source_ocr_content_fingerprint": source_ocr_content_fingerprint,
        "source_text_artifact_id": source_text_artifact_id,
        "source_text_content_fingerprint": source_text_content_fingerprint,
        "type": "pagetrace_structure",
    }
    return f"structure-sha256-{hashlib.sha256(_canonical_json(payload)).hexdigest()}"


def structure_content_fingerprint_for(pages: tuple[StructuredPage, ...]) -> str:
    """Fingerprint the complete canonical positioned page representation."""

    return hashlib.sha256(_canonical_json([_page_payload(page) for page in pages])).hexdigest()


def _processor_payload(processor: StructureProcessorDescriptor) -> dict[str, object]:
    return {
        "name": processor.name,
        "pdf_layout_backend_name": processor.pdf_layout_backend_name,
        "pdf_layout_backend_version": processor.pdf_layout_backend_version,
        "version": processor.version,
    }


def _configuration_payload(configuration: StructureConfig) -> dict[str, object]:
    return {
        "coordinate_precision": configuration.coordinate_precision,
        "limits": {
            "max_cells_per_document": configuration.limits.max_cells_per_document,
            "max_cells_per_table": configuration.limits.max_cells_per_table,
            "max_spans_per_document": configuration.limits.max_spans_per_document,
            "max_spans_per_page": configuration.limits.max_spans_per_page,
            "max_tables_per_document": configuration.limits.max_tables_per_document,
            "max_tables_per_page": configuration.limits.max_tables_per_page,
        },
        "table_horizontal_strategy": configuration.table_horizontal_strategy.value,
        "table_vertical_strategy": configuration.table_vertical_strategy.value,
        "word_x_tolerance": float(configuration.word_x_tolerance),
        "word_y_tolerance": float(configuration.word_y_tolerance),
    }


def _page_payload(page: StructuredPage) -> dict[str, object]:
    return {
        "coordinate_origin": page.coordinate_origin.value,
        "dimension_unit": page.dimension_unit.value,
        "height": float(page.height),
        "page_id": page.page_id,
        "page_number": page.page_number,
        "source_rotation_degrees": page.source_rotation_degrees,
        "spans": [
            {
                "bounding_box": _box_payload(span.bounding_box),
                "confidence": (None if span.confidence is None else float(span.confidence)),
                "source": span.source.value,
                "span_id": span.span_id,
                "span_index": span.span_index,
                "text": span.text,
            }
            for span in page.spans
        ],
        "tables": [
            {
                "bounding_box": _box_payload(table.bounding_box),
                "cells": [
                    {
                        "bounding_box": _box_payload(cell.bounding_box),
                        "column_index": cell.column_index,
                        "row_index": cell.row_index,
                        "text": cell.text,
                    }
                    for cell in table.cells
                ],
                "column_count": table.column_count,
                "row_count": table.row_count,
                "table_id": table.table_id,
                "table_index": table.table_index,
            }
            for table in page.tables
        ],
        "width": float(page.width),
    }


def _box_payload(box: BoundingBox) -> dict[str, float]:
    return {
        "bottom": float(box.bottom),
        "top": float(box.top),
        "x0": float(box.x0),
        "x1": float(box.x1),
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
