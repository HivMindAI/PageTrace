"""Strict canonical JSON for structured document artifacts."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import cast

from pagetrace.documents import DimensionUnit
from pagetrace.structure.errors import StructureIntegrityError
from pagetrace.structure.models import (
    BoundingBox,
    CoordinateOrigin,
    StructureConfig,
    StructuredDocumentArtifact,
    StructuredPage,
    StructuredTable,
    StructureLimits,
    StructureProcessorDescriptor,
    TableCell,
    TableStrategy,
    TextSpan,
    TextSpanSource,
)

_ARTIFACT_FIELDS = {
    "schema_version",
    "artifact_id",
    "document_id",
    "document_fingerprint",
    "source_text_artifact_id",
    "source_text_content_fingerprint",
    "source_ocr_artifact_id",
    "source_ocr_content_fingerprint",
    "processor",
    "configuration",
    "page_count",
    "span_count",
    "table_count",
    "cell_count",
    "content_fingerprint",
    "pages",
}
_PROCESSOR_FIELDS = {
    "name",
    "version",
    "pdf_layout_backend_name",
    "pdf_layout_backend_version",
}
_CONFIGURATION_FIELDS = {
    "coordinate_precision",
    "word_x_tolerance",
    "word_y_tolerance",
    "table_vertical_strategy",
    "table_horizontal_strategy",
    "limits",
}
_LIMIT_FIELDS = {
    "max_spans_per_page",
    "max_spans_per_document",
    "max_tables_per_page",
    "max_tables_per_document",
    "max_cells_per_table",
    "max_cells_per_document",
}
_PAGE_FIELDS = {
    "page_id",
    "page_number",
    "width",
    "height",
    "dimension_unit",
    "coordinate_origin",
    "source_rotation_degrees",
    "spans",
    "tables",
}
_SPAN_FIELDS = {"span_id", "span_index", "source", "text", "bounding_box", "confidence"}
_TABLE_FIELDS = {
    "table_id",
    "table_index",
    "bounding_box",
    "row_count",
    "column_count",
    "cells",
}
_CELL_FIELDS = {"row_index", "column_index", "bounding_box", "text"}
_BOX_FIELDS = {"x0", "top", "x1", "bottom"}


def serialize_structured_document(artifact: StructuredDocumentArtifact) -> bytes:
    """Serialize one validated structured artifact as canonical UTF-8 JSON."""

    payload: dict[str, object] = {
        "artifact_id": artifact.artifact_id,
        "cell_count": artifact.cell_count,
        "configuration": {
            "coordinate_precision": artifact.configuration.coordinate_precision,
            "limits": {
                "max_cells_per_document": artifact.configuration.limits.max_cells_per_document,
                "max_cells_per_table": artifact.configuration.limits.max_cells_per_table,
                "max_spans_per_document": artifact.configuration.limits.max_spans_per_document,
                "max_spans_per_page": artifact.configuration.limits.max_spans_per_page,
                "max_tables_per_document": artifact.configuration.limits.max_tables_per_document,
                "max_tables_per_page": artifact.configuration.limits.max_tables_per_page,
            },
            "table_horizontal_strategy": artifact.configuration.table_horizontal_strategy.value,
            "table_vertical_strategy": artifact.configuration.table_vertical_strategy.value,
            "word_x_tolerance": float(artifact.configuration.word_x_tolerance),
            "word_y_tolerance": float(artifact.configuration.word_y_tolerance),
        },
        "content_fingerprint": artifact.content_fingerprint,
        "document_fingerprint": artifact.document_fingerprint,
        "document_id": artifact.document_id,
        "page_count": artifact.page_count,
        "pages": [_serialize_page(page) for page in artifact.pages],
        "processor": {
            "name": artifact.processor.name,
            "pdf_layout_backend_name": artifact.processor.pdf_layout_backend_name,
            "pdf_layout_backend_version": artifact.processor.pdf_layout_backend_version,
            "version": artifact.processor.version,
        },
        "schema_version": artifact.schema_version,
        "source_ocr_artifact_id": artifact.source_ocr_artifact_id,
        "source_ocr_content_fingerprint": artifact.source_ocr_content_fingerprint,
        "source_text_artifact_id": artifact.source_text_artifact_id,
        "source_text_content_fingerprint": artifact.source_text_content_fingerprint,
        "span_count": artifact.span_count,
        "table_count": artifact.table_count,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{text}\n".encode()


def deserialize_structured_document(data: bytes) -> StructuredDocumentArtifact:
    """Parse and fully validate strict structured-artifact JSON."""

    try:
        value: object = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StructureIntegrityError("structured artifact is not valid UTF-8 JSON") from exc
    artifact = _mapping(value, "structured artifact")
    _require_exact_fields(artifact, _ARTIFACT_FIELDS, "structured artifact")
    processor_value = _mapping(artifact["processor"], "processor")
    _require_exact_fields(processor_value, _PROCESSOR_FIELDS, "processor")
    configuration_value = _mapping(artifact["configuration"], "configuration")
    _require_exact_fields(configuration_value, _CONFIGURATION_FIELDS, "configuration")
    limits_value = _mapping(configuration_value["limits"], "configuration.limits")
    _require_exact_fields(limits_value, _LIMIT_FIELDS, "configuration.limits")
    pages_value = _array(artifact["pages"], "pages")

    try:
        processor = StructureProcessorDescriptor(
            name=_string(processor_value["name"], "processor.name"),
            version=_string(processor_value["version"], "processor.version"),
            pdf_layout_backend_name=_optional_string(
                processor_value["pdf_layout_backend_name"],
                "processor.pdf_layout_backend_name",
            ),
            pdf_layout_backend_version=_optional_string(
                processor_value["pdf_layout_backend_version"],
                "processor.pdf_layout_backend_version",
            ),
        )
        configuration = StructureConfig(
            coordinate_precision=_integer(
                configuration_value["coordinate_precision"],
                "configuration.coordinate_precision",
            ),
            word_x_tolerance=_number(
                configuration_value["word_x_tolerance"], "configuration.word_x_tolerance"
            ),
            word_y_tolerance=_number(
                configuration_value["word_y_tolerance"], "configuration.word_y_tolerance"
            ),
            table_vertical_strategy=TableStrategy(
                _string(
                    configuration_value["table_vertical_strategy"],
                    "configuration.table_vertical_strategy",
                )
            ),
            table_horizontal_strategy=TableStrategy(
                _string(
                    configuration_value["table_horizontal_strategy"],
                    "configuration.table_horizontal_strategy",
                )
            ),
            limits=StructureLimits(
                max_spans_per_page=_integer(
                    limits_value["max_spans_per_page"],
                    "configuration.limits.max_spans_per_page",
                ),
                max_spans_per_document=_integer(
                    limits_value["max_spans_per_document"],
                    "configuration.limits.max_spans_per_document",
                ),
                max_tables_per_page=_integer(
                    limits_value["max_tables_per_page"],
                    "configuration.limits.max_tables_per_page",
                ),
                max_tables_per_document=_integer(
                    limits_value["max_tables_per_document"],
                    "configuration.limits.max_tables_per_document",
                ),
                max_cells_per_table=_integer(
                    limits_value["max_cells_per_table"],
                    "configuration.limits.max_cells_per_table",
                ),
                max_cells_per_document=_integer(
                    limits_value["max_cells_per_document"],
                    "configuration.limits.max_cells_per_document",
                ),
            ),
        )
        pages = tuple(_parse_page(item) for item in pages_value)
        return StructuredDocumentArtifact(
            schema_version=_integer(artifact["schema_version"], "schema_version"),
            artifact_id=_string(artifact["artifact_id"], "artifact_id"),
            document_id=_string(artifact["document_id"], "document_id"),
            document_fingerprint=_string(artifact["document_fingerprint"], "document_fingerprint"),
            source_text_artifact_id=_string(
                artifact["source_text_artifact_id"], "source_text_artifact_id"
            ),
            source_text_content_fingerprint=_string(
                artifact["source_text_content_fingerprint"],
                "source_text_content_fingerprint",
            ),
            source_ocr_artifact_id=_string(
                artifact["source_ocr_artifact_id"], "source_ocr_artifact_id"
            ),
            source_ocr_content_fingerprint=_string(
                artifact["source_ocr_content_fingerprint"],
                "source_ocr_content_fingerprint",
            ),
            processor=processor,
            configuration=configuration,
            page_count=_integer(artifact["page_count"], "page_count"),
            span_count=_integer(artifact["span_count"], "span_count"),
            table_count=_integer(artifact["table_count"], "table_count"),
            cell_count=_integer(artifact["cell_count"], "cell_count"),
            content_fingerprint=_string(artifact["content_fingerprint"], "content_fingerprint"),
            pages=pages,
        )
    except (TypeError, ValueError) as exc:
        raise StructureIntegrityError(f"invalid structured artifact value: {exc}") from exc


def _serialize_page(page: StructuredPage) -> dict[str, object]:
    return {
        "coordinate_origin": page.coordinate_origin.value,
        "dimension_unit": page.dimension_unit.value,
        "height": float(page.height),
        "page_id": page.page_id,
        "page_number": page.page_number,
        "source_rotation_degrees": page.source_rotation_degrees,
        "spans": [
            {
                "bounding_box": _serialize_box(span.bounding_box),
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
                "bounding_box": _serialize_box(table.bounding_box),
                "cells": [
                    {
                        "bounding_box": _serialize_box(cell.bounding_box),
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


def _parse_page(value: object) -> StructuredPage:
    page = _mapping(value, "structured page")
    _require_exact_fields(page, _PAGE_FIELDS, "structured page")
    spans = _array(page["spans"], "page.spans")
    tables = _array(page["tables"], "page.tables")
    return StructuredPage(
        page_id=_string(page["page_id"], "page.page_id"),
        page_number=_integer(page["page_number"], "page.page_number"),
        width=_number(page["width"], "page.width"),
        height=_number(page["height"], "page.height"),
        dimension_unit=DimensionUnit(_string(page["dimension_unit"], "page.dimension_unit")),
        coordinate_origin=CoordinateOrigin(
            _string(page["coordinate_origin"], "page.coordinate_origin")
        ),
        source_rotation_degrees=_optional_integer(
            page["source_rotation_degrees"], "page.source_rotation_degrees"
        ),
        spans=tuple(_parse_span(item) for item in spans),
        tables=tuple(_parse_table(item) for item in tables),
    )


def _parse_span(value: object) -> TextSpan:
    span = _mapping(value, "text span")
    _require_exact_fields(span, _SPAN_FIELDS, "text span")
    return TextSpan(
        span_id=_string(span["span_id"], "span.span_id"),
        span_index=_integer(span["span_index"], "span.span_index"),
        source=TextSpanSource(_string(span["source"], "span.source")),
        text=_string(span["text"], "span.text"),
        bounding_box=_parse_box(span["bounding_box"], "span.bounding_box"),
        confidence=_optional_number(span["confidence"], "span.confidence"),
    )


def _parse_table(value: object) -> StructuredTable:
    table = _mapping(value, "structured table")
    _require_exact_fields(table, _TABLE_FIELDS, "structured table")
    cells = _array(table["cells"], "table.cells")
    return StructuredTable(
        table_id=_string(table["table_id"], "table.table_id"),
        table_index=_integer(table["table_index"], "table.table_index"),
        bounding_box=_parse_box(table["bounding_box"], "table.bounding_box"),
        row_count=_integer(table["row_count"], "table.row_count"),
        column_count=_integer(table["column_count"], "table.column_count"),
        cells=tuple(_parse_cell(item) for item in cells),
    )


def _parse_cell(value: object) -> TableCell:
    cell = _mapping(value, "table cell")
    _require_exact_fields(cell, _CELL_FIELDS, "table cell")
    return TableCell(
        row_index=_integer(cell["row_index"], "cell.row_index"),
        column_index=_integer(cell["column_index"], "cell.column_index"),
        bounding_box=_parse_box(cell["bounding_box"], "cell.bounding_box"),
        text=_optional_string(cell["text"], "cell.text"),
    )


def _serialize_box(box: BoundingBox) -> dict[str, float]:
    return {
        "bottom": float(box.bottom),
        "top": float(box.top),
        "x0": float(box.x0),
        "x1": float(box.x1),
    }


def _parse_box(value: object, name: str) -> BoundingBox:
    box = _mapping(value, name)
    _require_exact_fields(box, _BOX_FIELDS, name)
    return BoundingBox(
        x0=_number(box["x0"], f"{name}.x0"),
        top=_number(box["top"], f"{name}.top"),
        x1=_number(box["x1"], f"{name}.x1"),
        bottom=_number(box["bottom"], f"{name}.bottom"),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise StructureIntegrityError(f"{name} must be a JSON object with string keys")
    return cast(dict[str, object], value)


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise StructureIntegrityError(f"{name} must be a JSON array")
    return value


def _require_exact_fields(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        raise StructureIntegrityError(
            f"{name} fields are invalid; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise StructureIntegrityError(f"{name} must be a string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StructureIntegrityError(f"{name} must be an integer")
    return value


def _optional_integer(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, name)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise StructureIntegrityError(f"{name} must be a finite number")
    return float(value)


def _optional_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    return _number(value, name)
