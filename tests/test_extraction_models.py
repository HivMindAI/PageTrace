from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import pytest

from pagetrace.documents.models import document_id_for, page_id_for
from pagetrace.extraction import (
    DEFAULT_EXTRACTION_LIMITS,
    EXTRACTION_SCHEMA_VERSION,
    ExtractionIntegrityError,
    ExtractionLimits,
    ExtractionMethod,
    ExtractorDescriptor,
    PageTextResult,
    PageTextStatus,
    PdfExtractionMode,
    TextExtractionArtifact,
    TextExtractionConfig,
    deserialize_text_extraction,
    serialize_text_extraction,
)
from pagetrace.extraction.models import artifact_id_for, content_fingerprint_for


def test_extractor_descriptor_rejects_false_or_missing_provenance() -> None:
    descriptor = _descriptor()

    with pytest.raises(ValueError, match="extractor name"):
        replace(descriptor, name="something-else")
    with pytest.raises(ValueError, match="extractor version"):
        replace(descriptor, version="")
    with pytest.raises(ValueError, match="backend name"):
        replace(descriptor, pdf_backend_name="not-pypdf")
    with pytest.raises(ValueError, match="backend version"):
        replace(descriptor, pdf_backend_version="")


def test_configuration_requires_a_typed_supported_mode() -> None:
    invalid_mode = cast(PdfExtractionMode, "layout")

    with pytest.raises(ValueError, match="supported mode"):
        TextExtractionConfig(pdf_extraction_mode=invalid_mode)
    with pytest.raises(ValueError, match="ExtractionLimits"):
        TextExtractionConfig(limits=cast(ExtractionLimits, object()))


def test_extraction_limits_have_validated_central_defaults() -> None:
    assert DEFAULT_EXTRACTION_LIMITS.max_characters_per_page == 2_000_000
    assert DEFAULT_EXTRACTION_LIMITS.max_characters_per_document == 20_000_000

    with pytest.raises(ValueError, match="max_characters_per_page"):
        ExtractionLimits(max_characters_per_page=0)
    with pytest.raises(ValueError, match="max_characters_per_document"):
        ExtractionLimits(max_characters_per_document=-1)
    with pytest.raises(ValueError, match="positive integer"):
        ExtractionLimits(max_characters_per_page=True)
    with pytest.raises(ValueError, match="positive integer"):
        ExtractionLimits(max_characters_per_document=cast(int, "100"))


def test_page_result_validates_counts_and_text_presence() -> None:
    embedded = _page(text="Text", status=PageTextStatus.EMBEDDED_TEXT)

    with pytest.raises(ValueError, match="character_count"):
        replace(embedded, character_count=-1)
    with pytest.raises(ValueError, match="non_whitespace_character_count"):
        replace(embedded, non_whitespace_character_count=5)
    with pytest.raises(ValueError, match="character_count does not match"):
        replace(embedded, character_count=5)
    with pytest.raises(ValueError, match="non_whitespace_character_count does not match"):
        replace(embedded, non_whitespace_character_count=3)
    with pytest.raises(ValueError, match="embedded-text pages"):
        replace(embedded, text=None, character_count=0, non_whitespace_character_count=0)
    with pytest.raises(ValueError, match="OCR-candidate"):
        replace(embedded, status=PageTextStatus.OCR_CANDIDATE)
    with pytest.raises(ValueError, match="routing-only"):
        replace(embedded, method=ExtractionMethod.OCR_ROUTING_ONLY)


def test_page_result_rejects_invalid_number_enum_values_and_absent_counts() -> None:
    candidate = _page(text=None, status=PageTextStatus.OCR_CANDIDATE)

    with pytest.raises(ValueError, match="page_number"):
        replace(candidate, page_number=0)
    with pytest.raises(ValueError, match="supported extraction method"):
        replace(candidate, method=cast(ExtractionMethod, "invalid"))
    with pytest.raises(ValueError, match="supported page text status"):
        replace(candidate, status=cast(PageTextStatus, "invalid"))
    with pytest.raises(ValueError, match="absent text"):
        replace(candidate, character_count=1, non_whitespace_character_count=1)


def test_artifact_validates_schema_identity_collection_and_content() -> None:
    artifact = _artifact()

    with pytest.raises(ValueError, match="schema version"):
        replace(artifact, schema_version=2)
    with pytest.raises(ValueError, match="canonical text artifact"):
        replace(artifact, artifact_id="unsafe")
    with pytest.raises(ValueError, match="canonical SHA-256"):
        replace(artifact, document_fingerprint="invalid")
    with pytest.raises(ValueError, match="does not match document_fingerprint"):
        replace(artifact, document_id=document_id_for("b" * 64))
    with pytest.raises(ValueError, match="extraction inputs"):
        replace(artifact, artifact_id=f"text-sha256-{'0' * 64}")
    with pytest.raises(ValueError, match="immutable tuple"):
        replace(artifact, pages=cast(tuple[PageTextResult, ...], [artifact.pages[0]]))
    with pytest.raises(ValueError, match="page_count"):
        replace(artifact, page_count=2)
    with pytest.raises(ValueError, match="canonical SHA-256"):
        replace(artifact, content_fingerprint="invalid")
    with pytest.raises(ValueError, match="does not match page results"):
        replace(artifact, content_fingerprint="0" * 64)


def test_artifact_validates_page_sequence_identity_and_threshold_status() -> None:
    artifact = _artifact()
    document_id = artifact.document_id
    wrong_number = _page(
        text="Text",
        status=PageTextStatus.EMBEDDED_TEXT,
        page_number=2,
        page_id=page_id_for(document_id, 2),
    )
    wrong_id = replace(artifact.pages[0], page_id="wrong-page-id")
    sparse_at_threshold = replace(artifact.pages[0], status=PageTextStatus.SPARSE_EMBEDDED_TEXT)
    embedded_below_threshold = _page(
        text="A", status=PageTextStatus.EMBEDDED_TEXT, page_id=page_id_for(document_id, 1)
    )

    with pytest.raises(ValueError, match="contiguous"):
        _replace_pages(artifact, (wrong_number,))
    with pytest.raises(ValueError, match="page_id"):
        _replace_pages(artifact, (wrong_id,))
    with pytest.raises(ValueError, match="sparse text"):
        _replace_pages(artifact, (sparse_at_threshold,))
    with pytest.raises(ValueError, match="embedded text"):
        _replace_pages(artifact, (embedded_below_threshold,))


def test_artifact_identity_rejects_invalid_source_fingerprint() -> None:
    with pytest.raises(ValueError, match="canonical SHA-256"):
        artifact_id_for("invalid", _descriptor(), TextExtractionConfig())


def test_deserializer_requires_objects_exact_fields_arrays_and_typed_scalars() -> None:
    artifact = _artifact()
    payload = json.loads(serialize_text_extraction(artifact))

    with pytest.raises(ExtractionIntegrityError, match="JSON object"):
        deserialize_text_extraction(b"[]")

    missing = dict(payload)
    missing.pop("artifact_id")
    with pytest.raises(ExtractionIntegrityError, match="fields are invalid"):
        deserialize_text_extraction(_json_bytes(missing))

    invalid_extractor = dict(payload)
    invalid_extractor["extractor"] = []
    with pytest.raises(ExtractionIntegrityError, match="extractor must be"):
        deserialize_text_extraction(_json_bytes(invalid_extractor))

    invalid_configuration = dict(payload)
    invalid_configuration["configuration"] = []
    with pytest.raises(ExtractionIntegrityError, match="configuration must be"):
        deserialize_text_extraction(_json_bytes(invalid_configuration))

    invalid_pages = dict(payload)
    invalid_pages["pages"] = {}
    with pytest.raises(ExtractionIntegrityError, match="pages must be a JSON array"):
        deserialize_text_extraction(_json_bytes(invalid_pages))

    invalid_page = dict(payload)
    invalid_page["pages"] = [[]]
    with pytest.raises(ExtractionIntegrityError, match="page result must be"):
        deserialize_text_extraction(_json_bytes(invalid_page))

    invalid_text = json.loads(serialize_text_extraction(artifact))
    invalid_text["pages"][0]["text"] = 7
    with pytest.raises(ExtractionIntegrityError, match=r"page.text must be a string"):
        deserialize_text_extraction(_json_bytes(invalid_text))

    boolean_schema = dict(payload)
    boolean_schema["schema_version"] = True
    with pytest.raises(ExtractionIntegrityError, match="schema_version must be an integer"):
        deserialize_text_extraction(_json_bytes(boolean_schema))


def _descriptor() -> ExtractorDescriptor:
    return ExtractorDescriptor(
        name="pagetrace-embedded-text-router",
        version="1",
        pdf_backend_name="pypdf",
        pdf_backend_version="6.0.0",
    )


def _page(
    *,
    text: str | None,
    status: PageTextStatus,
    page_number: int = 1,
    page_id: str | None = None,
) -> PageTextResult:
    fingerprint = "a" * 64
    actual_page_id = page_id or page_id_for(document_id_for(fingerprint), page_number)
    character_count = len(text) if text is not None else 0
    non_whitespace_count = (
        sum(not character.isspace() for character in text) if text is not None else 0
    )
    return PageTextResult(
        page_id=actual_page_id,
        page_number=page_number,
        method=ExtractionMethod.PYPDF_EMBEDDED_TEXT,
        status=status,
        text=text,
        character_count=character_count,
        non_whitespace_character_count=non_whitespace_count,
    )


def _artifact() -> TextExtractionArtifact:
    fingerprint = "a" * 64
    descriptor = _descriptor()
    configuration = TextExtractionConfig()
    pages = (_page(text="Text", status=PageTextStatus.EMBEDDED_TEXT),)
    return TextExtractionArtifact(
        schema_version=EXTRACTION_SCHEMA_VERSION,
        artifact_id=artifact_id_for(fingerprint, descriptor, configuration),
        document_id=document_id_for(fingerprint),
        document_fingerprint=fingerprint,
        extractor=descriptor,
        configuration=configuration,
        page_count=1,
        content_fingerprint=content_fingerprint_for(pages),
        pages=pages,
    )


def _replace_pages(
    artifact: TextExtractionArtifact, pages: tuple[PageTextResult, ...]
) -> TextExtractionArtifact:
    return replace(
        artifact,
        pages=pages,
        page_count=len(pages),
        content_fingerprint=content_fingerprint_for(pages),
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
