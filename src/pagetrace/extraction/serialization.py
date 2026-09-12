"""Canonical JSON serialization for immutable text extraction artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from pagetrace.extraction.errors import ExtractionIntegrityError
from pagetrace.extraction.models import (
    ExtractionLimits,
    ExtractionMethod,
    ExtractorDescriptor,
    PageTextResult,
    PageTextStatus,
    PdfExtractionMode,
    TextExtractionArtifact,
    TextExtractionConfig,
)

_ARTIFACT_FIELDS = {
    "schema_version",
    "artifact_id",
    "document_id",
    "document_fingerprint",
    "extractor",
    "configuration",
    "page_count",
    "content_fingerprint",
    "pages",
}
_EXTRACTOR_FIELDS = {"name", "version", "pdf_backend_name", "pdf_backend_version"}
_CONFIGURATION_FIELDS = {"pdf_extraction_mode", "minimum_embedded_characters", "limits"}
_LIMIT_FIELDS = {"max_characters_per_page", "max_characters_per_document"}
_PAGE_FIELDS = {
    "page_id",
    "page_number",
    "method",
    "status",
    "text",
    "character_count",
    "non_whitespace_character_count",
}


def serialize_text_extraction(artifact: TextExtractionArtifact) -> bytes:
    """Serialize an extraction artifact to canonical UTF-8 JSON plus one newline."""

    payload: dict[str, object] = {
        "schema_version": artifact.schema_version,
        "artifact_id": artifact.artifact_id,
        "document_id": artifact.document_id,
        "document_fingerprint": artifact.document_fingerprint,
        "extractor": {
            "name": artifact.extractor.name,
            "version": artifact.extractor.version,
            "pdf_backend_name": artifact.extractor.pdf_backend_name,
            "pdf_backend_version": artifact.extractor.pdf_backend_version,
        },
        "configuration": {
            "pdf_extraction_mode": artifact.configuration.pdf_extraction_mode.value,
            "minimum_embedded_characters": (artifact.configuration.minimum_embedded_characters),
            "limits": {
                "max_characters_per_page": (artifact.configuration.limits.max_characters_per_page),
                "max_characters_per_document": (
                    artifact.configuration.limits.max_characters_per_document
                ),
            },
        },
        "page_count": artifact.page_count,
        "content_fingerprint": artifact.content_fingerprint,
        "pages": [
            {
                "page_id": page.page_id,
                "page_number": page.page_number,
                "method": page.method.value,
                "status": page.status.value,
                "text": page.text,
                "character_count": page.character_count,
                "non_whitespace_character_count": page.non_whitespace_character_count,
            }
            for page in artifact.pages
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{text}\n".encode()


def deserialize_text_extraction(data: bytes) -> TextExtractionArtifact:
    """Parse and fully validate canonical extraction artifact bytes."""

    try:
        value: object = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExtractionIntegrityError("text artifact is not valid UTF-8 JSON") from exc

    artifact = _mapping(value, "text artifact")
    _require_exact_fields(artifact, _ARTIFACT_FIELDS, "text artifact")
    extractor_value = _mapping(artifact["extractor"], "extractor")
    _require_exact_fields(extractor_value, _EXTRACTOR_FIELDS, "extractor")
    configuration_value = _mapping(artifact["configuration"], "configuration")
    _require_exact_fields(configuration_value, _CONFIGURATION_FIELDS, "configuration")
    limits_value = _mapping(configuration_value["limits"], "configuration.limits")
    _require_exact_fields(limits_value, _LIMIT_FIELDS, "configuration.limits")
    pages_value = artifact["pages"]
    if not isinstance(pages_value, list):
        raise ExtractionIntegrityError("pages must be a JSON array")

    try:
        extractor = ExtractorDescriptor(
            name=_string(extractor_value["name"], "extractor.name"),
            version=_string(extractor_value["version"], "extractor.version"),
            pdf_backend_name=_string(
                extractor_value["pdf_backend_name"], "extractor.pdf_backend_name"
            ),
            pdf_backend_version=_string(
                extractor_value["pdf_backend_version"], "extractor.pdf_backend_version"
            ),
        )
        configuration = TextExtractionConfig(
            pdf_extraction_mode=PdfExtractionMode(
                _string(
                    configuration_value["pdf_extraction_mode"],
                    "configuration.pdf_extraction_mode",
                )
            ),
            minimum_embedded_characters=_integer(
                configuration_value["minimum_embedded_characters"],
                "configuration.minimum_embedded_characters",
            ),
            limits=ExtractionLimits(
                max_characters_per_page=_integer(
                    limits_value["max_characters_per_page"],
                    "configuration.limits.max_characters_per_page",
                ),
                max_characters_per_document=_integer(
                    limits_value["max_characters_per_document"],
                    "configuration.limits.max_characters_per_document",
                ),
            ),
        )
        pages = tuple(_parse_page(item) for item in pages_value)
        return TextExtractionArtifact(
            schema_version=_integer(artifact["schema_version"], "schema_version"),
            artifact_id=_string(artifact["artifact_id"], "artifact_id"),
            document_id=_string(artifact["document_id"], "document_id"),
            document_fingerprint=_string(artifact["document_fingerprint"], "document_fingerprint"),
            extractor=extractor,
            configuration=configuration,
            page_count=_integer(artifact["page_count"], "page_count"),
            content_fingerprint=_string(artifact["content_fingerprint"], "content_fingerprint"),
            pages=pages,
        )
    except (TypeError, ValueError) as exc:
        raise ExtractionIntegrityError(f"invalid text artifact value: {exc}") from exc


def _parse_page(value: object) -> PageTextResult:
    page = _mapping(value, "page result")
    _require_exact_fields(page, _PAGE_FIELDS, "page result")
    text_value = page["text"]
    text = None if text_value is None else _string(text_value, "page.text")
    return PageTextResult(
        page_id=_string(page["page_id"], "page.page_id"),
        page_number=_integer(page["page_number"], "page.page_number"),
        method=ExtractionMethod(_string(page["method"], "page.method")),
        status=PageTextStatus(_string(page["status"], "page.status")),
        text=text,
        character_count=_integer(page["character_count"], "page.character_count"),
        non_whitespace_character_count=_integer(
            page["non_whitespace_character_count"],
            "page.non_whitespace_character_count",
        ),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ExtractionIntegrityError(f"{name} must be a JSON object with string keys")
    return cast(dict[str, object], value)


def _require_exact_fields(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ExtractionIntegrityError(
            f"{name} fields are invalid; missing={missing}, unexpected={unexpected}"
        )


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ExtractionIntegrityError(f"{name} must be a string")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExtractionIntegrityError(f"{name} must be an integer")
    return value
