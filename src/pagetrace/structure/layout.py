"""Lazy, bounded pdfplumber adapter for embedded words and vector tables."""

from __future__ import annotations

import importlib
import math
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from numbers import Real
from typing import Any

from pagetrace.documents import DocumentManifest, MediaType
from pagetrace.structure.errors import (
    StructureDependencyError,
    StructureLimitError,
    StructureProcessingError,
)
from pagetrace.structure.models import (
    PDF_LAYOUT_BACKEND_NAME,
    STRUCTURE_PROCESSOR_NAME,
    STRUCTURE_PROCESSOR_VERSION,
    BoundingBox,
    StructureConfig,
    StructureProcessorDescriptor,
    TableCell,
)

_LAYOUT_FAILURES = (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError)


@dataclass(frozen=True, slots=True)
class PositionedWord:
    """One validated word returned in display-oriented PDF points."""

    text: str
    bounding_box: BoundingBox


@dataclass(frozen=True, slots=True)
class PositionedTable:
    """One validated detected table before stable artifact IDs are assigned."""

    bounding_box: BoundingBox
    row_count: int
    column_count: int
    cells: tuple[TableCell, ...]


@dataclass(frozen=True, slots=True)
class PdfPageLayout:
    """Display dimensions, positioned words, and tables for one PDF page."""

    width: float
    height: float
    words: tuple[PositionedWord, ...]
    tables: tuple[PositionedTable, ...]


def current_structure_processor_descriptor(media_type: MediaType) -> StructureProcessorDescriptor:
    """Capture the version of the optional PDF layout backend when applicable."""

    if media_type is not MediaType.PDF:
        return StructureProcessorDescriptor(
            name=STRUCTURE_PROCESSOR_NAME,
            version=STRUCTURE_PROCESSOR_VERSION,
            pdf_layout_backend_name=None,
            pdf_layout_backend_version=None,
        )
    try:
        backend_version = version(PDF_LAYOUT_BACKEND_NAME)
    except PackageNotFoundError as exc:
        raise StructureDependencyError(
            "PDF structure extraction is unavailable; install PageTrace with the 'structure' extra"
        ) from exc
    return StructureProcessorDescriptor(
        name=STRUCTURE_PROCESSOR_NAME,
        version=STRUCTURE_PROCESSOR_VERSION,
        pdf_layout_backend_name=PDF_LAYOUT_BACKEND_NAME,
        pdf_layout_backend_version=backend_version,
    )


def extract_pdf_layout(
    source_bytes: bytes,
    manifest: DocumentManifest,
    configuration: StructureConfig,
) -> tuple[PdfPageLayout, ...]:
    """Extract bounded words and vector tables from all verified PDF pages."""

    if manifest.media_type is not MediaType.PDF:
        raise StructureProcessingError("PDF layout extraction requires a PDF document")
    try:
        pdfplumber = importlib.import_module(PDF_LAYOUT_BACKEND_NAME)
    except ImportError as exc:
        raise StructureDependencyError(
            "PDF structure extraction is unavailable; install PageTrace with the 'structure' extra"
        ) from exc

    pages: list[PdfPageLayout] = []
    total_spans = 0
    total_tables = 0
    total_cells = 0
    try:
        with pdfplumber.open(BytesIO(source_bytes)) as document:
            if len(document.pages) != manifest.page_count:
                raise StructureProcessingError(
                    "pdfplumber page count does not match the verified document manifest"
                )
            for page_manifest, page in zip(manifest.pages, document.pages, strict=True):
                width = _coordinate(page.width, configuration)
                height = _coordinate(page.height, configuration)
                expected_width, expected_height = _display_dimensions(page_manifest)
                if not math.isclose(
                    width, expected_width, abs_tol=10**-configuration.coordinate_precision
                ):
                    raise StructureProcessingError(
                        f"pdfplumber width does not match verified page {page_manifest.page_number}"
                    )
                if not math.isclose(
                    height,
                    expected_height,
                    abs_tol=10**-configuration.coordinate_precision,
                ):
                    raise StructureProcessingError(
                        "pdfplumber height does not match verified page "
                        f"{page_manifest.page_number}"
                    )

                words = _extract_words(page, width, height, configuration)
                total_spans += len(words)
                if len(words) > configuration.limits.max_spans_per_page:
                    raise StructureLimitError(
                        f"page {page_manifest.page_number} exceeds the structured span limit"
                    )
                if total_spans > configuration.limits.max_spans_per_document:
                    raise StructureLimitError("document exceeds the structured span limit")

                tables = _extract_tables(page, width, height, configuration)
                total_tables += len(tables)
                page_cells = sum(len(table.cells) for table in tables)
                total_cells += page_cells
                if len(tables) > configuration.limits.max_tables_per_page:
                    raise StructureLimitError(
                        f"page {page_manifest.page_number} exceeds the structured table limit"
                    )
                if total_tables > configuration.limits.max_tables_per_document:
                    raise StructureLimitError("document exceeds the structured table limit")
                if total_cells > configuration.limits.max_cells_per_document:
                    raise StructureLimitError("document exceeds the structured cell limit")
                pages.append(PdfPageLayout(width, height, words, tables))
    except (StructureDependencyError, StructureLimitError, StructureProcessingError):
        raise
    except _LAYOUT_FAILURES as exc:
        raise StructureProcessingError("pdfplumber could not extract verified PDF layout") from exc
    return tuple(pages)


def _extract_words(
    page: Any,
    width: float,
    height: float,
    configuration: StructureConfig,
) -> tuple[PositionedWord, ...]:
    raw_words = page.extract_words(
        x_tolerance=float(configuration.word_x_tolerance),
        y_tolerance=float(configuration.word_y_tolerance),
        keep_blank_chars=False,
        use_text_flow=False,
        split_at_punctuation=False,
        expand_ligatures=True,
        return_chars=False,
    )
    if not isinstance(raw_words, list):
        raise StructureProcessingError("pdfplumber returned invalid word output")
    words: list[PositionedWord] = []
    for raw_word in raw_words:
        if not isinstance(raw_word, dict):
            raise StructureProcessingError("pdfplumber returned an invalid word")
        text = raw_word.get("text")
        if not isinstance(text, str) or not text.strip():
            raise StructureProcessingError("pdfplumber returned an invalid word text")
        box = _box(raw_word, width, height, configuration, "word")
        words.append(PositionedWord(text=text, bounding_box=box))
    return tuple(words)


def _extract_tables(
    page: Any,
    width: float,
    height: float,
    configuration: StructureConfig,
) -> tuple[PositionedTable, ...]:
    settings = {
        "horizontal_strategy": configuration.table_horizontal_strategy.value,
        "vertical_strategy": configuration.table_vertical_strategy.value,
    }
    raw_tables = page.find_tables(table_settings=settings)
    if not isinstance(raw_tables, list):
        raise StructureProcessingError("pdfplumber returned invalid table output")
    raw_tables.sort(key=lambda table: tuple(float(value) for value in table.bbox))
    tables: list[PositionedTable] = []
    for raw_table in raw_tables:
        table_box = _box_from_sequence(
            raw_table.bbox,
            width,
            height,
            configuration,
            "table",
        )
        extracted_rows = raw_table.extract(
            x_tolerance=float(configuration.word_x_tolerance),
            y_tolerance=float(configuration.word_y_tolerance),
        )
        raw_rows = tuple(raw_table.rows)
        if not isinstance(extracted_rows, list) or len(extracted_rows) != len(raw_rows):
            raise StructureProcessingError("pdfplumber returned inconsistent table rows")
        row_count = len(raw_rows)
        column_count = max((len(tuple(row.cells)) for row in raw_rows), default=0)
        if row_count < 1 or column_count < 1:
            raise StructureProcessingError("pdfplumber returned an empty table grid")

        cells: list[TableCell] = []
        for row_index, (raw_row, extracted_row) in enumerate(
            zip(raw_rows, extracted_rows, strict=True), start=1
        ):
            raw_cells = tuple(raw_row.cells)
            if not isinstance(extracted_row, list) or len(extracted_row) != len(raw_cells):
                raise StructureProcessingError("pdfplumber returned inconsistent table cells")
            for column_index, (raw_cell, text) in enumerate(
                zip(raw_cells, extracted_row, strict=True), start=1
            ):
                if raw_cell is None:
                    continue
                cell_box = _box_from_sequence(
                    raw_cell,
                    width,
                    height,
                    configuration,
                    "table cell",
                )
                if not cell_box.within_box(table_box):
                    raise StructureProcessingError(
                        "pdfplumber returned a cell outside its table bounds"
                    )
                if text is not None and not isinstance(text, str):
                    raise StructureProcessingError("pdfplumber returned invalid table cell text")
                accepted_text = text if isinstance(text, str) and text.strip() else None
                cells.append(TableCell(row_index, column_index, cell_box, accepted_text))
        if len(cells) > configuration.limits.max_cells_per_table:
            raise StructureLimitError("detected table exceeds the structured cell limit")
        tables.append(PositionedTable(table_box, row_count, column_count, tuple(cells)))
    return tuple(tables)


def _box(
    value: dict[str, object],
    width: float,
    height: float,
    configuration: StructureConfig,
    name: str,
) -> BoundingBox:
    try:
        coordinates = value["x0"], value["top"], value["x1"], value["bottom"]
    except KeyError as exc:
        raise StructureProcessingError(f"pdfplumber {name} has incomplete coordinates") from exc
    return _box_from_sequence(coordinates, width, height, configuration, name)


def _box_from_sequence(
    value: object,
    width: float,
    height: float,
    configuration: StructureConfig,
    name: str,
) -> BoundingBox:
    if not isinstance(value, Iterable):
        raise StructureProcessingError(f"pdfplumber {name} box is not iterable")
    coordinates: tuple[object, ...] = tuple(value)
    if len(coordinates) != 4:
        raise StructureProcessingError(f"pdfplumber {name} box must contain four coordinates")
    try:
        box = BoundingBox(*(_coordinate(item, configuration) for item in coordinates))
    except ValueError as exc:
        raise StructureProcessingError(f"pdfplumber {name} box is invalid") from exc
    if not box.within(width, height):
        raise StructureProcessingError(f"pdfplumber {name} box is outside the page")
    return box


def _coordinate(value: object, configuration: StructureConfig) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise StructureProcessingError("pdfplumber returned a non-finite coordinate")
    result = round(float(value), configuration.coordinate_precision)
    return 0.0 if result == 0 else result


def _display_dimensions(page: Any) -> tuple[float, float]:
    width = float(page.width)
    height = float(page.height)
    if page.rotation_degrees in (90, 270):
        return height, width
    return width, height
