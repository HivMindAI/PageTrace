from __future__ import annotations

from dataclasses import replace

import pytest

from pagetrace.documents.models import document_id_for, page_id_for
from pagetrace.extraction import PageTextStatus
from pagetrace.ocr import (
    DEFAULT_OCR_CONFIG,
    OCR_SCHEMA_VERSION,
    OcrArtifact,
    OcrConfig,
    OcrLimits,
    OcrMethod,
    OcrPageResult,
    OcrPageStatus,
    OcrProcessorDescriptor,
    OcrRoutingPolicy,
    deserialize_ocr_artifact,
    is_ocr_artifact_id,
    ocr_artifact_id_for,
    ocr_content_fingerprint_for,
    serialize_ocr_artifact,
)

_FINGERPRINT = "1" * 64
_DOCUMENT_ID = document_id_for(_FINGERPRINT)
_TEXT_ARTIFACT_ID = f"text-sha256-{'2' * 64}"
_TEXT_CONTENT_FINGERPRINT = "3" * 64


def test_default_ocr_configuration_is_bounded_and_routes_sparse_pages() -> None:
    assert DEFAULT_OCR_CONFIG.routing_policy is OcrRoutingPolicy.CANDIDATES_AND_SPARSE
    assert DEFAULT_OCR_CONFIG.render_dpi == 200
    assert DEFAULT_OCR_CONFIG.engine_max_side_length == 2_000
    assert DEFAULT_OCR_CONFIG.minimum_confidence == 0.5
    assert DEFAULT_OCR_CONFIG.limits.max_pages_per_document == 100
    assert DEFAULT_OCR_CONFIG.limits.max_pixels_per_page == 25_000_000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_pages_per_document", 0),
        ("max_pixels_per_page", -1),
        ("max_pixels_per_document", True),
        ("max_lines_per_page", "100"),
        ("max_characters_per_page", 0),
        ("max_characters_per_document", -5),
    ],
)
def test_ocr_limits_require_positive_integers(field: str, value: object) -> None:
    values: dict[str, object] = {
        "max_pages_per_document": 1,
        "max_pixels_per_page": 1,
        "max_pixels_per_document": 1,
        "max_lines_per_page": 1,
        "max_characters_per_page": 1,
        "max_characters_per_document": 1,
    }
    values[field] = value

    with pytest.raises(ValueError, match="positive integer"):
        OcrLimits(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("render_dpi", 0, "positive integer"),
        ("render_dpi", True, "positive integer"),
        ("engine_max_side_length", -1, "positive integer"),
        ("minimum_confidence", -0.1, "from 0 to 1"),
        ("minimum_confidence", 1.1, "from 0 to 1"),
        ("minimum_confidence", True, "from 0 to 1"),
    ],
)
def test_ocr_configuration_rejects_invalid_values(field: str, value: object, message: str) -> None:
    values: dict[str, object] = {
        "render_dpi": 200,
        "engine_max_side_length": 2_000,
        "minimum_confidence": 0.5,
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        OcrConfig(**values)  # type: ignore[arg-type]


def test_ocr_page_result_is_immutable_and_validates_text_statistics() -> None:
    page = _ocr_text_page()

    assert page.text == "PageTrace"
    with pytest.raises(AttributeError):
        page.text = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="character_count"):
        replace(page, character_count=1)


def test_unselected_page_cannot_claim_rendering_or_text() -> None:
    with pytest.raises(ValueError, match="unselected"):
        OcrPageResult(
            page_id=page_id_for(_DOCUMENT_ID, 1),
            page_number=1,
            source_status=PageTextStatus.EMBEDDED_TEXT,
            method=OcrMethod.NOT_APPLIED,
            status=OcrPageStatus.NOT_SELECTED,
            text=None,
            character_count=0,
            non_whitespace_character_count=0,
            line_count=0,
            mean_confidence=None,
            rendered_width_pixels=100,
            rendered_height_pixels=100,
        )


def test_ocr_no_text_page_requires_selected_method_and_dimensions() -> None:
    page = _ocr_no_text_page()

    assert page.status is OcrPageStatus.OCR_NO_TEXT
    with pytest.raises(ValueError, match="selected pages"):
        replace(page, method=OcrMethod.NOT_APPLIED)


def test_artifact_identity_changes_with_routing_and_model_bytes() -> None:
    processor = _processor()
    candidates_only = OcrConfig(routing_policy=OcrRoutingPolicy.CANDIDATES_ONLY)
    first = ocr_artifact_id_for(
        _FINGERPRINT,
        _TEXT_ARTIFACT_ID,
        _TEXT_CONTENT_FINGERPRINT,
        processor,
        DEFAULT_OCR_CONFIG,
    )
    second = ocr_artifact_id_for(
        _FINGERPRINT,
        _TEXT_ARTIFACT_ID,
        _TEXT_CONTENT_FINGERPRINT,
        processor,
        candidates_only,
    )
    third = ocr_artifact_id_for(
        _FINGERPRINT,
        _TEXT_ARTIFACT_ID,
        _TEXT_CONTENT_FINGERPRINT,
        replace(processor, model_fingerprint="4" * 64),
        DEFAULT_OCR_CONFIG,
    )

    assert is_ocr_artifact_id(first)
    assert len({first, second, third}) == 3


def test_ocr_artifact_round_trips_canonical_json_exactly() -> None:
    artifact = _artifact()
    serialized = serialize_ocr_artifact(artifact)

    assert deserialize_ocr_artifact(serialized) == artifact
    assert serialize_ocr_artifact(deserialize_ocr_artifact(serialized)) == serialized
    assert serialized.endswith(b"\n")


def test_artifact_rejects_page_selection_that_conflicts_with_policy() -> None:
    artifact = _artifact()
    page = replace(
        artifact.pages[0],
        source_status=PageTextStatus.EMBEDDED_TEXT,
    )
    pages = (page,)

    with pytest.raises(ValueError, match="routing policy"):
        replace(
            artifact,
            pages=pages,
            content_fingerprint=ocr_content_fingerprint_for(pages),
        )


def test_artifact_rejects_tampered_content_fingerprint() -> None:
    with pytest.raises(ValueError, match="content_fingerprint"):
        replace(_artifact(), content_fingerprint="5" * 64)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "other", "processor name"),
        ("version", "", "version"),
        ("engine_name", "other", "engine name"),
        ("engine_version", "", "engine version"),
        ("inference_backend_name", "other", "backend name"),
        ("inference_backend_version", "", "backend version"),
        ("inference_profile", "other", "inference profile"),
        ("model_profile", "other", "model profile"),
        ("model_fingerprint", "bad", "model_fingerprint"),
        ("pdf_renderer_name", "pypdfium2", "both be present"),
        ("pdf_renderer_name", "other", "PDF renderer name"),
        ("pdf_renderer_version", "", "both be present"),
    ],
)
def test_processor_descriptor_rejects_invalid_provenance(
    field: str, value: object, message: str
) -> None:
    processor = _processor()
    changes: dict[str, object] = {field: value}
    if field == "pdf_renderer_name" and value == "other":
        changes["pdf_renderer_version"] = "1"

    with pytest.raises(ValueError, match=message):
        replace(processor, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"page_number": True}, "page_number"),
        ({"page_number": 0}, "page_number"),
        ({"source_status": "bad"}, "source_status"),
        ({"method": "bad"}, "method and status"),
        ({"character_count": -1}, "non-negative"),
        ({"non_whitespace_character_count": 10}, "cannot exceed"),
        ({"text": None}, "absent OCR text"),
        ({"text": ""}, "character_count"),
        (
            {
                "text": "Page Trace",
                "character_count": 10,
                "non_whitespace_character_count": 8,
            },
            "non_whitespace",
        ),
        ({"line_count": 0}, "at least one"),
        ({"mean_confidence": float("nan")}, "mean_confidence"),
        ({"rendered_height_pixels": None}, "rendered dimensions"),
        ({"rendered_width_pixels": 0}, "rendered dimensions"),
        ({"status": OcrPageStatus.OCR_NO_TEXT}, "OCR-no-text"),
    ],
)
def test_ocr_page_rejects_inconsistent_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_ocr_text_page(), **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema_version": 2}, "schema version"),
        ({"artifact_id": "bad"}, "artifact_id"),
        ({"document_fingerprint": "bad"}, "document_fingerprint"),
        ({"document_id": document_id_for("9" * 64)}, "document_id"),
        ({"source_text_artifact_id": "bad"}, "source_text_artifact_id"),
        ({"source_text_content_fingerprint": "bad"}, "source_text_content_fingerprint"),
        ({"page_count": 2}, "page_count"),
        ({"selected_page_count": 0}, "selected_page_count"),
        ({"content_fingerprint": "bad"}, "content_fingerprint"),
    ],
)
def test_ocr_artifact_rejects_invalid_structure(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_artifact(), **changes)  # type: ignore[arg-type]


def test_ocr_artifact_requires_immutable_page_tuple() -> None:
    with pytest.raises(ValueError, match="immutable tuple"):
        replace(_artifact(), pages=[_ocr_text_page()])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("document_fingerprint", "text_artifact_id", "text_fingerprint", "message"),
    [
        ("bad", _TEXT_ARTIFACT_ID, _TEXT_CONTENT_FINGERPRINT, "document_fingerprint"),
        (_FINGERPRINT, "bad", _TEXT_CONTENT_FINGERPRINT, "source_text_artifact_id"),
        (_FINGERPRINT, _TEXT_ARTIFACT_ID, "bad", "source_text_content_fingerprint"),
    ],
)
def test_ocr_identity_rejects_noncanonical_inputs(
    document_fingerprint: str,
    text_artifact_id: str,
    text_fingerprint: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ocr_artifact_id_for(
            document_fingerprint,
            text_artifact_id,
            text_fingerprint,
            _processor(),
            DEFAULT_OCR_CONFIG,
        )


def _processor() -> OcrProcessorDescriptor:
    return OcrProcessorDescriptor(
        name="pagetrace-routed-ocr",
        version="1",
        engine_name="rapidocr",
        engine_version="3.9.2",
        inference_backend_name="onnxruntime",
        inference_backend_version="1.30.0",
        inference_profile="cpu-single-thread",
        model_profile="pp-ocrv6-small-ch-cls-v4-mobile",
        model_fingerprint="6" * 64,
        pdf_renderer_name=None,
        pdf_renderer_version=None,
    )


def _ocr_text_page() -> OcrPageResult:
    return OcrPageResult(
        page_id=page_id_for(_DOCUMENT_ID, 1),
        page_number=1,
        source_status=PageTextStatus.OCR_CANDIDATE,
        method=OcrMethod.RAPIDOCR,
        status=OcrPageStatus.OCR_TEXT,
        text="PageTrace",
        character_count=9,
        non_whitespace_character_count=9,
        line_count=1,
        mean_confidence=0.95,
        rendered_width_pixels=800,
        rendered_height_pixels=600,
    )


def _ocr_no_text_page() -> OcrPageResult:
    return OcrPageResult(
        page_id=page_id_for(_DOCUMENT_ID, 1),
        page_number=1,
        source_status=PageTextStatus.OCR_CANDIDATE,
        method=OcrMethod.RAPIDOCR,
        status=OcrPageStatus.OCR_NO_TEXT,
        text=None,
        character_count=0,
        non_whitespace_character_count=0,
        line_count=0,
        mean_confidence=None,
        rendered_width_pixels=800,
        rendered_height_pixels=600,
    )


def _artifact() -> OcrArtifact:
    processor = _processor()
    pages = (_ocr_text_page(),)
    return OcrArtifact(
        schema_version=OCR_SCHEMA_VERSION,
        artifact_id=ocr_artifact_id_for(
            _FINGERPRINT,
            _TEXT_ARTIFACT_ID,
            _TEXT_CONTENT_FINGERPRINT,
            processor,
            DEFAULT_OCR_CONFIG,
        ),
        document_id=_DOCUMENT_ID,
        document_fingerprint=_FINGERPRINT,
        source_text_artifact_id=_TEXT_ARTIFACT_ID,
        source_text_content_fingerprint=_TEXT_CONTENT_FINGERPRINT,
        processor=processor,
        configuration=DEFAULT_OCR_CONFIG,
        page_count=1,
        selected_page_count=1,
        content_fingerprint=ocr_content_fingerprint_for(pages),
        pages=pages,
    )
