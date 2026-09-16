from __future__ import annotations

from dataclasses import replace

import pytest

from pagetrace.documents import DimensionUnit
from pagetrace.documents.models import document_id_for, page_id_for
from pagetrace.structure import (
    DEFAULT_STRUCTURE_CONFIG,
    STRUCTURE_SCHEMA_VERSION,
    BoundingBox,
    CoordinateOrigin,
    StructureConfig,
    StructuredDocumentArtifact,
    StructuredPage,
    StructuredTable,
    StructureLimits,
    StructureProcessorDescriptor,
    TableCell,
    TextSpan,
    TextSpanSource,
    deserialize_structured_document,
    is_structure_artifact_id,
    serialize_structured_document,
    span_id_for,
    structure_artifact_id_for,
    structure_content_fingerprint_for,
    table_id_for,
)

_FINGERPRINT = "1" * 64
_DOCUMENT_ID = document_id_for(_FINGERPRINT)
_TEXT_ID = f"text-sha256-{'2' * 64}"
_TEXT_FINGERPRINT = "3" * 64
_OCR_ID = f"ocr-sha256-{'4' * 64}"
_OCR_FINGERPRINT = "5" * 64


def test_default_structure_configuration_is_explicit_and_bounded() -> None:
    assert DEFAULT_STRUCTURE_CONFIG.coordinate_precision == 6
    assert DEFAULT_STRUCTURE_CONFIG.word_x_tolerance == 3
    assert DEFAULT_STRUCTURE_CONFIG.limits.max_spans_per_page == 100_000
    assert DEFAULT_STRUCTURE_CONFIG.limits.max_cells_per_document == 100_000


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("coordinate_precision", -1, "0 to 9"),
        ("coordinate_precision", True, "0 to 9"),
        ("word_x_tolerance", -1.0, "non-negative"),
        ("word_y_tolerance", float("nan"), "non-negative"),
    ],
)
def test_structure_configuration_rejects_invalid_values(
    field: str, value: object, message: str
) -> None:
    values: dict[str, object] = {
        "coordinate_precision": 6,
        "word_x_tolerance": 3.0,
        "word_y_tolerance": 3.0,
    }
    values[field] = value
    with pytest.raises(ValueError, match=message):
        StructureConfig(**values)  # type: ignore[arg-type]


def test_structure_configuration_requires_typed_strategies_and_limits() -> None:
    with pytest.raises(ValueError, match="strategies"):
        StructureConfig(table_vertical_strategy="lines")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="StructureLimits"):
        StructureConfig(limits="limits")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "wrong"}, "processor name"),
        ({"version": ""}, "version"),
        ({"pdf_layout_backend_name": "pdfplumber"}, "both be present"),
        (
            {"pdf_layout_backend_name": "other", "pdf_layout_backend_version": "1"},
            "backend name",
        ),
        (
            {"pdf_layout_backend_name": "pdfplumber", "pdf_layout_backend_version": ""},
            "version",
        ),
    ],
)
def test_processor_descriptor_rejects_invalid_contract(
    changes: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "name": "pagetrace-structured-document",
        "version": "1",
        "pdf_layout_backend_name": None,
        "pdf_layout_backend_version": None,
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        StructureProcessorDescriptor(**values)  # type: ignore[arg-type]


def test_bounding_boxes_require_positive_in_page_area() -> None:
    box = BoundingBox(1, 2, 3, 4)

    assert box.within(3, 4)
    assert box.within_box(BoundingBox(0, 0, 5, 5))
    with pytest.raises(ValueError, match="positive area"):
        BoundingBox(2, 2, 1, 4)
    with pytest.raises(ValueError, match="finite"):
        BoundingBox(0, 0, float("inf"), 4)


@pytest.mark.parametrize(
    "field",
    [
        "max_spans_per_page",
        "max_spans_per_document",
        "max_tables_per_page",
        "max_tables_per_document",
        "max_cells_per_table",
        "max_cells_per_document",
    ],
)
def test_structure_limits_require_positive_integers(field: str) -> None:
    values: dict[str, object] = {
        "max_spans_per_page": 1,
        "max_spans_per_document": 1,
        "max_tables_per_page": 1,
        "max_tables_per_document": 1,
        "max_cells_per_table": 1,
        "max_cells_per_document": 1,
    }
    values[field] = 0
    with pytest.raises(ValueError, match="positive integer"):
        StructureLimits(**values)  # type: ignore[arg-type]


def test_text_span_source_controls_confidence_semantics() -> None:
    page_id = page_id_for(_DOCUMENT_ID, 1)
    embedded = TextSpan(
        span_id_for(page_id, TextSpanSource.EMBEDDED_WORD, 1),
        1,
        TextSpanSource.EMBEDDED_WORD,
        "word",
        BoundingBox(1, 1, 10, 10),
        None,
    )
    assert embedded.confidence is None

    with pytest.raises(ValueError, match="confidence"):
        replace(embedded, confidence=0.9)
    with pytest.raises(ValueError, match="confidence"):
        replace(embedded, source=TextSpanSource.OCR_LINE)


def test_structured_artifact_round_trips_canonical_json() -> None:
    artifact = _artifact()
    serialized = serialize_structured_document(artifact)

    assert deserialize_structured_document(serialized) == artifact
    assert serialize_structured_document(deserialize_structured_document(serialized)) == serialized
    assert serialized.endswith(b"\n")


def test_structure_identity_changes_with_precision_and_backend() -> None:
    artifact = _artifact()
    changed_config = structure_artifact_id_for(
        _FINGERPRINT,
        _TEXT_ID,
        _TEXT_FINGERPRINT,
        _OCR_ID,
        _OCR_FINGERPRINT,
        artifact.processor,
        StructureConfig(coordinate_precision=5),
    )
    changed_backend = structure_artifact_id_for(
        _FINGERPRINT,
        _TEXT_ID,
        _TEXT_FINGERPRINT,
        _OCR_ID,
        _OCR_FINGERPRINT,
        replace(artifact.processor, pdf_layout_backend_version="0.11.10"),
        DEFAULT_STRUCTURE_CONFIG,
    )

    assert is_structure_artifact_id(artifact.artifact_id)
    assert len({artifact.artifact_id, changed_config, changed_backend}) == 3


def test_page_rejects_out_of_bounds_span() -> None:
    artifact = _artifact()
    span = replace(artifact.pages[0].spans[0], bounding_box=BoundingBox(1, 1, 500, 10))
    with pytest.raises(ValueError, match="inside the page"):
        replace(artifact.pages[0], spans=(span,))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"span_index": 0}, "span_index"),
        ({"source": "embedded_word"}, "source"),
        ({"text": " "}, "non-whitespace"),
        ({"bounding_box": "box"}, "BoundingBox"),
    ],
)
def test_text_span_rejects_invalid_shape(changes: dict[str, object], message: str) -> None:
    span = _artifact().pages[0].spans[0]

    with pytest.raises(ValueError, match=message):
        replace(span, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize("confidence", [None, True, -0.1, 1.1, float("nan")])
def test_ocr_span_requires_bounded_confidence(confidence: object) -> None:
    span = _artifact().pages[0].spans[0]

    with pytest.raises(ValueError, match="confidence"):
        replace(
            span,
            source=TextSpanSource.OCR_LINE,
            confidence=confidence,  # type: ignore[arg-type]
        )


def test_table_cells_and_grids_reject_inconsistent_values() -> None:
    table = _artifact().pages[0].tables[0]
    cell = table.cells[0]

    with pytest.raises(ValueError, match="row_index"):
        replace(cell, row_index=0)
    with pytest.raises(ValueError, match="BoundingBox"):
        replace(cell, bounding_box="box")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-whitespace"):
        replace(cell, text=" ")
    with pytest.raises(ValueError, match="table_index"):
        replace(table, table_index=0)
    with pytest.raises(ValueError, match="immutable tuple"):
        replace(table, cells=[cell])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        replace(table, cells=(cell, cell))
    with pytest.raises(ValueError, match="declared grid"):
        replace(table, cells=(replace(cell, row_index=2),))
    with pytest.raises(ValueError, match="inside the table"):
        replace(table, cells=(replace(cell, bounding_box=BoundingBox(0, 0, 200, 120)),))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"page_number": 0}, "page_number"),
        ({"width": 0}, "positive finite"),
        ({"height": float("inf")}, "positive finite"),
        ({"dimension_unit": "points"}, "points or pixels"),
        ({"coordinate_origin": "top_left"}, "top_left"),
        ({"source_rotation_degrees": 45}, "rotation"),
        ({"spans": []}, "immutable tuples"),
    ],
)
def test_structured_page_rejects_invalid_shape(changes: dict[str, object], message: str) -> None:
    page = _artifact().pages[0]

    with pytest.raises(ValueError, match=message):
        replace(page, **changes)  # type: ignore[arg-type]


def test_structured_page_rejects_inconsistent_span_and_table_identity() -> None:
    page = _artifact().pages[0]
    span = page.spans[0]
    table = page.tables[0]

    with pytest.raises(ValueError, match="contiguous"):
        replace(page, spans=(replace(span, span_index=2),))
    with pytest.raises(ValueError, match="span_id"):
        replace(page, spans=(replace(span, span_id="wrong"),))
    with pytest.raises(ValueError, match="contiguous"):
        replace(page, tables=(replace(table, table_index=2),))
    with pytest.raises(ValueError, match="table_id"):
        replace(page, tables=(replace(table, table_id="wrong"),))
    with pytest.raises(ValueError, match="inside the page"):
        replace(page, tables=(replace(table, bounding_box=BoundingBox(10, 40, 250, 100)),))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema_version": 2}, "schema version"),
        ({"artifact_id": "unsafe"}, "artifact_id"),
        ({"document_fingerprint": "bad"}, "document_fingerprint"),
        ({"document_id": f"sha256-{'0' * 64}"}, "document_id"),
        ({"source_text_artifact_id": "bad"}, "source_text_artifact_id"),
        ({"source_text_content_fingerprint": "bad"}, "source_text_content_fingerprint"),
        ({"source_ocr_artifact_id": "bad"}, "source_ocr_artifact_id"),
        ({"source_ocr_content_fingerprint": "bad"}, "source_ocr_content_fingerprint"),
        ({"artifact_id": f"structure-sha256-{'0' * 64}"}, "structure inputs"),
        ({"pages": []}, "immutable tuple"),
        ({"page_count": 2}, "page_count"),
        ({"content_fingerprint": "bad"}, "content_fingerprint"),
        ({"content_fingerprint": "0" * 64}, "structured pages"),
        ({"span_count": 2}, "totals"),
    ],
)
def test_structured_artifact_rejects_invalid_contract(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_artifact(), **changes)  # type: ignore[arg-type]


def test_structure_identifiers_reject_invalid_inputs() -> None:
    artifact = _artifact()

    with pytest.raises(ValueError, match="span_index"):
        span_id_for(artifact.pages[0].page_id, TextSpanSource.EMBEDDED_WORD, 0)
    with pytest.raises(ValueError, match="table_index"):
        table_id_for(artifact.pages[0].page_id, 0)
    with pytest.raises(ValueError, match="document_fingerprint"):
        structure_artifact_id_for(
            "bad",
            _TEXT_ID,
            _TEXT_FINGERPRINT,
            _OCR_ID,
            _OCR_FINGERPRINT,
            artifact.processor,
            artifact.configuration,
        )
    with pytest.raises(ValueError, match="source_text_artifact_id"):
        structure_artifact_id_for(
            _FINGERPRINT,
            "bad",
            _TEXT_FINGERPRINT,
            _OCR_ID,
            _OCR_FINGERPRINT,
            artifact.processor,
            artifact.configuration,
        )
    with pytest.raises(ValueError, match="source_text_content_fingerprint"):
        structure_artifact_id_for(
            _FINGERPRINT,
            _TEXT_ID,
            "bad",
            _OCR_ID,
            _OCR_FINGERPRINT,
            artifact.processor,
            artifact.configuration,
        )
    with pytest.raises(ValueError, match="source_ocr_artifact_id"):
        structure_artifact_id_for(
            _FINGERPRINT,
            _TEXT_ID,
            _TEXT_FINGERPRINT,
            "bad",
            _OCR_FINGERPRINT,
            artifact.processor,
            artifact.configuration,
        )
    with pytest.raises(ValueError, match="source_ocr_content_fingerprint"):
        structure_artifact_id_for(
            _FINGERPRINT,
            _TEXT_ID,
            _TEXT_FINGERPRINT,
            _OCR_ID,
            "bad",
            artifact.processor,
            artifact.configuration,
        )


def _artifact() -> StructuredDocumentArtifact:
    processor = StructureProcessorDescriptor(
        name="pagetrace-structured-document",
        version="1",
        pdf_layout_backend_name="pdfplumber",
        pdf_layout_backend_version="0.11.9",
    )
    page_id = page_id_for(_DOCUMENT_ID, 1)
    span = TextSpan(
        span_id=span_id_for(page_id, TextSpanSource.EMBEDDED_WORD, 1),
        span_index=1,
        source=TextSpanSource.EMBEDDED_WORD,
        text="PageTrace",
        bounding_box=BoundingBox(10, 10, 70, 24),
        confidence=None,
    )
    table_box = BoundingBox(10, 40, 190, 100)
    table = StructuredTable(
        table_id=table_id_for(page_id, 1),
        table_index=1,
        bounding_box=table_box,
        row_count=1,
        column_count=1,
        cells=(TableCell(1, 1, table_box, "value"),),
    )
    pages = (
        StructuredPage(
            page_id=page_id,
            page_number=1,
            width=200,
            height=200,
            dimension_unit=DimensionUnit.POINTS,
            coordinate_origin=CoordinateOrigin.TOP_LEFT,
            source_rotation_degrees=0,
            spans=(span,),
            tables=(table,),
        ),
    )
    return StructuredDocumentArtifact(
        schema_version=STRUCTURE_SCHEMA_VERSION,
        artifact_id=structure_artifact_id_for(
            _FINGERPRINT,
            _TEXT_ID,
            _TEXT_FINGERPRINT,
            _OCR_ID,
            _OCR_FINGERPRINT,
            processor,
            DEFAULT_STRUCTURE_CONFIG,
        ),
        document_id=_DOCUMENT_ID,
        document_fingerprint=_FINGERPRINT,
        source_text_artifact_id=_TEXT_ID,
        source_text_content_fingerprint=_TEXT_FINGERPRINT,
        source_ocr_artifact_id=_OCR_ID,
        source_ocr_content_fingerprint=_OCR_FINGERPRINT,
        processor=processor,
        configuration=DEFAULT_STRUCTURE_CONFIG,
        page_count=1,
        span_count=1,
        table_count=1,
        cell_count=1,
        content_fingerprint=structure_content_fingerprint_for(pages),
        pages=pages,
    )
