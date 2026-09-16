"""Canonical JSON serialization for immutable OCR artifacts."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import cast

from pagetrace.extraction.models import PageTextStatus
from pagetrace.ocr.errors import OcrIntegrityError
from pagetrace.ocr.models import (
    OcrArtifact,
    OcrConfig,
    OcrLimits,
    OcrMethod,
    OcrPageResult,
    OcrPageStatus,
    OcrProcessorDescriptor,
    OcrRoutingPolicy,
)

_ARTIFACT_FIELDS = {
    "schema_version",
    "artifact_id",
    "document_id",
    "document_fingerprint",
    "source_text_artifact_id",
    "source_text_content_fingerprint",
    "processor",
    "configuration",
    "page_count",
    "selected_page_count",
    "content_fingerprint",
    "pages",
}
_PROCESSOR_FIELDS = {
    "name",
    "version",
    "engine_name",
    "engine_version",
    "inference_backend_name",
    "inference_backend_version",
    "inference_profile",
    "model_profile",
    "model_fingerprint",
    "pdf_renderer_name",
    "pdf_renderer_version",
}
_CONFIGURATION_FIELDS = {
    "routing_policy",
    "render_dpi",
    "engine_max_side_length",
    "minimum_confidence",
    "limits",
}
_LIMIT_FIELDS = {
    "max_pages_per_document",
    "max_pixels_per_page",
    "max_pixels_per_document",
    "max_lines_per_page",
    "max_characters_per_page",
    "max_characters_per_document",
}
_PAGE_FIELDS = {
    "page_id",
    "page_number",
    "source_status",
    "method",
    "status",
    "text",
    "character_count",
    "non_whitespace_character_count",
    "line_count",
    "mean_confidence",
    "rendered_width_pixels",
    "rendered_height_pixels",
}


def serialize_ocr_artifact(artifact: OcrArtifact) -> bytes:
    """Serialize an OCR artifact to canonical UTF-8 JSON plus one newline."""

    payload: dict[str, object] = {
        "schema_version": artifact.schema_version,
        "artifact_id": artifact.artifact_id,
        "document_id": artifact.document_id,
        "document_fingerprint": artifact.document_fingerprint,
        "source_text_artifact_id": artifact.source_text_artifact_id,
        "source_text_content_fingerprint": artifact.source_text_content_fingerprint,
        "processor": {
            "name": artifact.processor.name,
            "version": artifact.processor.version,
            "engine_name": artifact.processor.engine_name,
            "engine_version": artifact.processor.engine_version,
            "inference_backend_name": artifact.processor.inference_backend_name,
            "inference_backend_version": artifact.processor.inference_backend_version,
            "inference_profile": artifact.processor.inference_profile,
            "model_profile": artifact.processor.model_profile,
            "model_fingerprint": artifact.processor.model_fingerprint,
            "pdf_renderer_name": artifact.processor.pdf_renderer_name,
            "pdf_renderer_version": artifact.processor.pdf_renderer_version,
        },
        "configuration": {
            "routing_policy": artifact.configuration.routing_policy.value,
            "render_dpi": artifact.configuration.render_dpi,
            "engine_max_side_length": artifact.configuration.engine_max_side_length,
            "minimum_confidence": float(artifact.configuration.minimum_confidence),
            "limits": {
                "max_pages_per_document": (artifact.configuration.limits.max_pages_per_document),
                "max_pixels_per_page": artifact.configuration.limits.max_pixels_per_page,
                "max_pixels_per_document": (artifact.configuration.limits.max_pixels_per_document),
                "max_lines_per_page": artifact.configuration.limits.max_lines_per_page,
                "max_characters_per_page": (artifact.configuration.limits.max_characters_per_page),
                "max_characters_per_document": (
                    artifact.configuration.limits.max_characters_per_document
                ),
            },
        },
        "page_count": artifact.page_count,
        "selected_page_count": artifact.selected_page_count,
        "content_fingerprint": artifact.content_fingerprint,
        "pages": [
            {
                "page_id": page.page_id,
                "page_number": page.page_number,
                "source_status": page.source_status.value,
                "method": page.method.value,
                "status": page.status.value,
                "text": page.text,
                "character_count": page.character_count,
                "non_whitespace_character_count": page.non_whitespace_character_count,
                "line_count": page.line_count,
                "mean_confidence": page.mean_confidence,
                "rendered_width_pixels": page.rendered_width_pixels,
                "rendered_height_pixels": page.rendered_height_pixels,
            }
            for page in artifact.pages
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{text}\n".encode()


def deserialize_ocr_artifact(data: bytes) -> OcrArtifact:
    """Parse and fully validate canonical OCR artifact bytes."""

    try:
        value: object = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OcrIntegrityError("OCR artifact is not valid UTF-8 JSON") from exc

    artifact = _mapping(value, "OCR artifact")
    _require_exact_fields(artifact, _ARTIFACT_FIELDS, "OCR artifact")
    processor_value = _mapping(artifact["processor"], "processor")
    _require_exact_fields(processor_value, _PROCESSOR_FIELDS, "processor")
    configuration_value = _mapping(artifact["configuration"], "configuration")
    _require_exact_fields(configuration_value, _CONFIGURATION_FIELDS, "configuration")
    limits_value = _mapping(configuration_value["limits"], "configuration.limits")
    _require_exact_fields(limits_value, _LIMIT_FIELDS, "configuration.limits")
    pages_value = artifact["pages"]
    if not isinstance(pages_value, list):
        raise OcrIntegrityError("pages must be a JSON array")

    try:
        processor = OcrProcessorDescriptor(
            name=_string(processor_value["name"], "processor.name"),
            version=_string(processor_value["version"], "processor.version"),
            engine_name=_string(processor_value["engine_name"], "processor.engine_name"),
            engine_version=_string(processor_value["engine_version"], "processor.engine_version"),
            inference_backend_name=_string(
                processor_value["inference_backend_name"],
                "processor.inference_backend_name",
            ),
            inference_backend_version=_string(
                processor_value["inference_backend_version"],
                "processor.inference_backend_version",
            ),
            inference_profile=_string(
                processor_value["inference_profile"], "processor.inference_profile"
            ),
            model_profile=_string(processor_value["model_profile"], "processor.model_profile"),
            model_fingerprint=_string(
                processor_value["model_fingerprint"], "processor.model_fingerprint"
            ),
            pdf_renderer_name=_optional_string(
                processor_value["pdf_renderer_name"], "processor.pdf_renderer_name"
            ),
            pdf_renderer_version=_optional_string(
                processor_value["pdf_renderer_version"], "processor.pdf_renderer_version"
            ),
        )
        configuration = OcrConfig(
            routing_policy=OcrRoutingPolicy(
                _string(configuration_value["routing_policy"], "configuration.routing_policy")
            ),
            render_dpi=_integer(configuration_value["render_dpi"], "configuration.render_dpi"),
            engine_max_side_length=_integer(
                configuration_value["engine_max_side_length"],
                "configuration.engine_max_side_length",
            ),
            minimum_confidence=_number(
                configuration_value["minimum_confidence"],
                "configuration.minimum_confidence",
            ),
            limits=OcrLimits(
                max_pages_per_document=_integer(
                    limits_value["max_pages_per_document"],
                    "configuration.limits.max_pages_per_document",
                ),
                max_pixels_per_page=_integer(
                    limits_value["max_pixels_per_page"],
                    "configuration.limits.max_pixels_per_page",
                ),
                max_pixels_per_document=_integer(
                    limits_value["max_pixels_per_document"],
                    "configuration.limits.max_pixels_per_document",
                ),
                max_lines_per_page=_integer(
                    limits_value["max_lines_per_page"],
                    "configuration.limits.max_lines_per_page",
                ),
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
        return OcrArtifact(
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
            processor=processor,
            configuration=configuration,
            page_count=_integer(artifact["page_count"], "page_count"),
            selected_page_count=_integer(artifact["selected_page_count"], "selected_page_count"),
            content_fingerprint=_string(artifact["content_fingerprint"], "content_fingerprint"),
            pages=pages,
        )
    except (TypeError, ValueError) as exc:
        raise OcrIntegrityError(f"invalid OCR artifact value: {exc}") from exc


def _parse_page(value: object) -> OcrPageResult:
    page = _mapping(value, "OCR page result")
    _require_exact_fields(page, _PAGE_FIELDS, "OCR page result")
    return OcrPageResult(
        page_id=_string(page["page_id"], "page.page_id"),
        page_number=_integer(page["page_number"], "page.page_number"),
        source_status=PageTextStatus(_string(page["source_status"], "page.source_status")),
        method=OcrMethod(_string(page["method"], "page.method")),
        status=OcrPageStatus(_string(page["status"], "page.status")),
        text=_optional_string(page["text"], "page.text"),
        character_count=_integer(page["character_count"], "page.character_count"),
        non_whitespace_character_count=_integer(
            page["non_whitespace_character_count"],
            "page.non_whitespace_character_count",
        ),
        line_count=_integer(page["line_count"], "page.line_count"),
        mean_confidence=_optional_number(page["mean_confidence"], "page.mean_confidence"),
        rendered_width_pixels=_optional_integer(
            page["rendered_width_pixels"], "page.rendered_width_pixels"
        ),
        rendered_height_pixels=_optional_integer(
            page["rendered_height_pixels"], "page.rendered_height_pixels"
        ),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise OcrIntegrityError(f"{name} must be a JSON object with string keys")
    return cast(dict[str, object], value)


def _require_exact_fields(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        raise OcrIntegrityError(
            f"{name} fields are invalid; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise OcrIntegrityError(f"{name} must be a string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OcrIntegrityError(f"{name} must be an integer")
    return value


def _optional_integer(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, name)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise OcrIntegrityError(f"{name} must be a finite number")
    return float(value)


def _optional_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    return _number(value, name)
