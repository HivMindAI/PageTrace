"""Immutable values for routed OCR processing and provenance."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum

from pagetrace.documents.models import document_id_for, is_sha256, page_id_for
from pagetrace.extraction.models import PageTextStatus, is_extraction_id

OCR_SCHEMA_VERSION = 1
OCR_PROCESSOR_NAME = "pagetrace-routed-ocr"
OCR_PROCESSOR_VERSION = "1"
OCR_ENGINE_NAME = "rapidocr"
OCR_INFERENCE_BACKEND_NAME = "onnxruntime"
OCR_INFERENCE_PROFILE = "cpu-single-thread"
PDF_RENDERER_NAME = "pypdfium2"
RAPIDOCR_MODEL_PROFILE = "pp-ocrv6-small-ch-cls-v4-mobile"
_OCR_ARTIFACT_ID_PATTERN = re.compile(r"^ocr-sha256-[0-9a-f]{64}$")


class OcrRoutingPolicy(StrEnum):
    """Which Milestone 2A page statuses are eligible for OCR."""

    CANDIDATES_ONLY = "ocr_candidates_only"
    CANDIDATES_AND_SPARSE = "ocr_candidates_and_sparse"


class OcrPageStatus(StrEnum):
    """Outcome of the OCR stage for one source page."""

    NOT_SELECTED = "not_selected"
    OCR_TEXT = "ocr_text"
    OCR_NO_TEXT = "ocr_no_text"


class OcrMethod(StrEnum):
    """Method actually applied to one page by this stage."""

    NOT_APPLIED = "not_applied"
    RAPIDOCR = "rapidocr"


@dataclass(frozen=True, slots=True)
class OcrLimits:
    """Bounds applied before rendering and after OCR backend return."""

    max_pages_per_document: int = 100
    max_pixels_per_page: int = 25_000_000
    max_pixels_per_document: int = 100_000_000
    max_lines_per_page: int = 1_000
    max_characters_per_page: int = 2_000_000
    max_characters_per_document: int = 20_000_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_pages_per_document", self.max_pages_per_document),
            ("max_pixels_per_page", self.max_pixels_per_page),
            ("max_pixels_per_document", self.max_pixels_per_document),
            ("max_lines_per_page", self.max_lines_per_page),
            ("max_characters_per_page", self.max_characters_per_page),
            ("max_characters_per_document", self.max_characters_per_document),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_OCR_LIMITS = OcrLimits()


@dataclass(frozen=True, slots=True)
class OcrConfig:
    """Output-affecting OCR routing, rendering, and confidence policy."""

    routing_policy: OcrRoutingPolicy = OcrRoutingPolicy.CANDIDATES_AND_SPARSE
    render_dpi: int = 200
    engine_max_side_length: int = 2_000
    minimum_confidence: float = 0.5
    limits: OcrLimits = DEFAULT_OCR_LIMITS

    def __post_init__(self) -> None:
        if not isinstance(self.routing_policy, OcrRoutingPolicy):
            raise ValueError("routing_policy must be a supported OCR routing policy")
        for name, value in (
            ("render_dpi", self.render_dpi),
            ("engine_max_side_length", self.engine_max_side_length),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.minimum_confidence, bool)
            or not isinstance(self.minimum_confidence, (int, float))
            or not math.isfinite(self.minimum_confidence)
            or not 0 <= self.minimum_confidence <= 1
        ):
            raise ValueError("minimum_confidence must be a finite number from 0 to 1")
        if not isinstance(self.limits, OcrLimits):
            raise ValueError("limits must be an OcrLimits value")


DEFAULT_OCR_CONFIG = OcrConfig()


@dataclass(frozen=True, slots=True)
class OcrProcessorDescriptor:
    """Version and model provenance for OCR, inference, and optional PDF rendering."""

    name: str
    version: str
    engine_name: str
    engine_version: str
    inference_backend_name: str
    inference_backend_version: str
    inference_profile: str
    model_profile: str
    model_fingerprint: str
    pdf_renderer_name: str | None
    pdf_renderer_version: str | None

    def __post_init__(self) -> None:
        if self.name != OCR_PROCESSOR_NAME:
            raise ValueError(f"OCR processor name must be {OCR_PROCESSOR_NAME}")
        if not self.version:
            raise ValueError("OCR processor version must not be empty")
        if self.engine_name != OCR_ENGINE_NAME:
            raise ValueError(f"OCR engine name must be {OCR_ENGINE_NAME}")
        if not self.engine_version:
            raise ValueError("OCR engine version must not be empty")
        if self.inference_backend_name != OCR_INFERENCE_BACKEND_NAME:
            raise ValueError(f"OCR inference backend name must be {OCR_INFERENCE_BACKEND_NAME}")
        if not self.inference_backend_version:
            raise ValueError("OCR inference backend version must not be empty")
        if self.inference_profile != OCR_INFERENCE_PROFILE:
            raise ValueError(f"OCR inference profile must be {OCR_INFERENCE_PROFILE}")
        if self.model_profile != RAPIDOCR_MODEL_PROFILE:
            raise ValueError(f"OCR model profile must be {RAPIDOCR_MODEL_PROFILE}")
        if not is_sha256(self.model_fingerprint):
            raise ValueError("model_fingerprint must be a canonical SHA-256 digest")
        if (self.pdf_renderer_name is None) != (self.pdf_renderer_version is None):
            raise ValueError("PDF renderer name and version must both be present or absent")
        if self.pdf_renderer_name is not None and self.pdf_renderer_name != PDF_RENDERER_NAME:
            raise ValueError(f"PDF renderer name must be {PDF_RENDERER_NAME}")
        if self.pdf_renderer_version == "":
            raise ValueError("PDF renderer version must not be empty")


@dataclass(frozen=True, slots=True)
class OcrPageResult:
    """OCR outcome and bounded statistics for one source page."""

    page_id: str
    page_number: int
    source_status: PageTextStatus
    method: OcrMethod
    status: OcrPageStatus
    text: str | None
    character_count: int
    non_whitespace_character_count: int
    line_count: int
    mean_confidence: float | None
    rendered_width_pixels: int | None
    rendered_height_pixels: int | None

    def __post_init__(self) -> None:
        if isinstance(self.page_number, bool) or not isinstance(self.page_number, int):
            raise ValueError("page_number must be a positive 1-based integer")
        if self.page_number < 1:
            raise ValueError("page_number must be a positive 1-based integer")
        if not isinstance(self.source_status, PageTextStatus):
            raise ValueError("source_status must be a Milestone 2A page status")
        if not isinstance(self.method, OcrMethod) or not isinstance(self.status, OcrPageStatus):
            raise ValueError("OCR method and status must be supported enum values")
        for name, value in (
            ("character_count", self.character_count),
            ("non_whitespace_character_count", self.non_whitespace_character_count),
            ("line_count", self.line_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.non_whitespace_character_count > self.character_count:
            raise ValueError("non_whitespace_character_count cannot exceed character_count")

        if self.text is None:
            if self.character_count or self.non_whitespace_character_count or self.line_count:
                raise ValueError("absent OCR text must have zero counts")
        else:
            if not self.text or self.character_count != len(self.text):
                raise ValueError("character_count must match non-empty OCR text")
            if self.non_whitespace_character_count != sum(
                not character.isspace() for character in self.text
            ):
                raise ValueError("non_whitespace_character_count does not match OCR text")
            if self.line_count < 1:
                raise ValueError("OCR text must have at least one source line")

        if self.mean_confidence is not None and (
            isinstance(self.mean_confidence, bool)
            or not isinstance(self.mean_confidence, (int, float))
            or not math.isfinite(self.mean_confidence)
            or not 0 <= self.mean_confidence <= 1
        ):
            raise ValueError("mean_confidence must be null or a finite number from 0 to 1")

        dimensions = (self.rendered_width_pixels, self.rendered_height_pixels)
        if any(value is not None for value in dimensions) and any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in dimensions
        ):
            raise ValueError("rendered dimensions must both be positive integers")

        if self.status is OcrPageStatus.NOT_SELECTED:
            if (
                self.method is not OcrMethod.NOT_APPLIED
                or self.text is not None
                or self.mean_confidence is not None
                or any(value is not None for value in dimensions)
            ):
                raise ValueError("unselected pages must not claim OCR processing")
        else:
            if self.method is not OcrMethod.RAPIDOCR or any(value is None for value in dimensions):
                raise ValueError("selected pages must record RapidOCR and rendered dimensions")
            if self.status is OcrPageStatus.OCR_TEXT:
                if self.text is None or self.mean_confidence is None:
                    raise ValueError("OCR text pages must record text and confidence")
            elif self.text is not None or self.mean_confidence is not None:
                raise ValueError("OCR-no-text pages must not claim text or confidence")


@dataclass(frozen=True, slots=True)
class OcrArtifact:
    """Canonical OCR artifact linked to a verified document and text-routing artifact."""

    schema_version: int
    artifact_id: str
    document_id: str
    document_fingerprint: str
    source_text_artifact_id: str
    source_text_content_fingerprint: str
    processor: OcrProcessorDescriptor
    configuration: OcrConfig
    page_count: int
    selected_page_count: int
    content_fingerprint: str
    pages: tuple[OcrPageResult, ...]

    def __post_init__(self) -> None:
        if self.schema_version != OCR_SCHEMA_VERSION:
            raise ValueError(f"unsupported OCR schema version: {self.schema_version}")
        if not is_ocr_artifact_id(self.artifact_id):
            raise ValueError("artifact_id is not a canonical OCR artifact identifier")
        if not is_sha256(self.document_fingerprint):
            raise ValueError("document_fingerprint must be a canonical SHA-256 digest")
        if self.document_id != document_id_for(self.document_fingerprint):
            raise ValueError("document_id does not match document_fingerprint")
        if not is_extraction_id(self.source_text_artifact_id):
            raise ValueError("source_text_artifact_id is not canonical")
        if not is_sha256(self.source_text_content_fingerprint):
            raise ValueError("source_text_content_fingerprint must be a SHA-256 digest")
        if self.artifact_id != ocr_artifact_id_for(
            self.document_fingerprint,
            self.source_text_artifact_id,
            self.source_text_content_fingerprint,
            self.processor,
            self.configuration,
        ):
            raise ValueError("artifact_id does not match OCR inputs")
        if not isinstance(self.pages, tuple):
            raise ValueError("pages must be an immutable tuple")
        if self.page_count != len(self.pages) or self.page_count < 1:
            raise ValueError("page_count must match a non-empty page collection")
        selected = sum(page.status is not OcrPageStatus.NOT_SELECTED for page in self.pages)
        if self.selected_page_count != selected:
            raise ValueError("selected_page_count does not match page results")
        if selected > self.configuration.limits.max_pages_per_document:
            raise ValueError("selected_page_count exceeds the configured OCR page limit")
        if not is_sha256(self.content_fingerprint):
            raise ValueError("content_fingerprint must be a canonical SHA-256 digest")
        if self.content_fingerprint != ocr_content_fingerprint_for(self.pages):
            raise ValueError("content_fingerprint does not match OCR page results")

        total_characters = 0
        total_pixels = 0
        for expected_number, page in enumerate(self.pages, start=1):
            if page.page_number != expected_number:
                raise ValueError("pages must use contiguous 1-based numbering")
            if page.page_id != page_id_for(self.document_id, expected_number):
                raise ValueError("page_id does not match document_id and page_number")
            should_select = page.source_status is PageTextStatus.OCR_CANDIDATE or (
                page.source_status is PageTextStatus.SPARSE_EMBEDDED_TEXT
                and self.configuration.routing_policy is OcrRoutingPolicy.CANDIDATES_AND_SPARSE
            )
            was_selected = page.status is not OcrPageStatus.NOT_SELECTED
            if should_select != was_selected:
                raise ValueError("OCR page selection contradicts the routing policy")
            if page.character_count > self.configuration.limits.max_characters_per_page:
                raise ValueError("OCR page text exceeds the configured character limit")
            if page.line_count > self.configuration.limits.max_lines_per_page:
                raise ValueError("OCR page output exceeds the configured line limit")
            total_characters += page.character_count
            if page.rendered_width_pixels is not None:
                if page.rendered_height_pixels is None:
                    raise ValueError("rendered page height is missing")
                pixels = page.rendered_width_pixels * page.rendered_height_pixels
                if pixels > self.configuration.limits.max_pixels_per_page:
                    raise ValueError("rendered page exceeds the configured pixel limit")
                total_pixels += pixels
        if total_characters > self.configuration.limits.max_characters_per_document:
            raise ValueError("OCR document text exceeds the configured character limit")
        if total_pixels > self.configuration.limits.max_pixels_per_document:
            raise ValueError("rendered document exceeds the configured pixel limit")


def is_ocr_artifact_id(value: str) -> bool:
    """Return whether *value* is a path-safe OCR artifact identifier."""

    return _OCR_ARTIFACT_ID_PATTERN.fullmatch(value) is not None


def ocr_artifact_id_for(
    document_fingerprint: str,
    source_text_artifact_id: str,
    source_text_content_fingerprint: str,
    processor: OcrProcessorDescriptor,
    configuration: OcrConfig,
) -> str:
    """Derive OCR identity from source, routing, backend, models, and configuration."""

    if not is_sha256(document_fingerprint):
        raise ValueError("document_fingerprint must be a canonical SHA-256 digest")
    if not is_extraction_id(source_text_artifact_id):
        raise ValueError("source_text_artifact_id must be canonical")
    if not is_sha256(source_text_content_fingerprint):
        raise ValueError("source_text_content_fingerprint must be a SHA-256 digest")
    payload = {
        "configuration": _configuration_payload(configuration),
        "document_fingerprint": document_fingerprint,
        "processor": _processor_payload(processor),
        "schema_version": OCR_SCHEMA_VERSION,
        "source_text_artifact_id": source_text_artifact_id,
        "source_text_content_fingerprint": source_text_content_fingerprint,
        "type": "pagetrace_ocr",
    }
    return f"ocr-sha256-{hashlib.sha256(_canonical_json(payload)).hexdigest()}"


def ocr_content_fingerprint_for(pages: tuple[OcrPageResult, ...]) -> str:
    """Fingerprint canonical OCR page results for integrity-checked readback."""

    payload = [
        {
            "character_count": page.character_count,
            "line_count": page.line_count,
            "mean_confidence": page.mean_confidence,
            "method": page.method.value,
            "non_whitespace_character_count": page.non_whitespace_character_count,
            "page_id": page.page_id,
            "page_number": page.page_number,
            "rendered_height_pixels": page.rendered_height_pixels,
            "rendered_width_pixels": page.rendered_width_pixels,
            "source_status": page.source_status.value,
            "status": page.status.value,
            "text": page.text,
        }
        for page in pages
    ]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _processor_payload(processor: OcrProcessorDescriptor) -> dict[str, object]:
    return {
        "engine_name": processor.engine_name,
        "engine_version": processor.engine_version,
        "inference_backend_name": processor.inference_backend_name,
        "inference_backend_version": processor.inference_backend_version,
        "inference_profile": processor.inference_profile,
        "model_fingerprint": processor.model_fingerprint,
        "model_profile": processor.model_profile,
        "name": processor.name,
        "pdf_renderer_name": processor.pdf_renderer_name,
        "pdf_renderer_version": processor.pdf_renderer_version,
        "version": processor.version,
    }


def _configuration_payload(configuration: OcrConfig) -> dict[str, object]:
    return {
        "engine_max_side_length": configuration.engine_max_side_length,
        "limits": {
            "max_characters_per_document": (configuration.limits.max_characters_per_document),
            "max_characters_per_page": configuration.limits.max_characters_per_page,
            "max_lines_per_page": configuration.limits.max_lines_per_page,
            "max_pages_per_document": configuration.limits.max_pages_per_document,
            "max_pixels_per_document": configuration.limits.max_pixels_per_document,
            "max_pixels_per_page": configuration.limits.max_pixels_per_page,
        },
        "minimum_confidence": float(configuration.minimum_confidence),
        "render_dpi": configuration.render_dpi,
        "routing_policy": configuration.routing_policy.value,
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
