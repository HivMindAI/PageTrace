"""Immutable values for deterministic text extraction and OCR routing."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from pagetrace.documents.models import document_id_for, is_sha256, page_id_for

EXTRACTION_SCHEMA_VERSION = 1
EXTRACTOR_NAME = "pagetrace-embedded-text-router"
EXTRACTOR_VERSION = "1"
PDF_BACKEND_NAME = "pypdf"
_ARTIFACT_ID_PATTERN = re.compile(r"^text-sha256-[0-9a-f]{64}$")


class PdfExtractionMode(StrEnum):
    """Supported pypdf text extraction modes."""

    PLAIN = "plain"


class PageTextStatus(StrEnum):
    """What the current digital-text stage established for one page.

    Sparse embedded text exists but is below the configured sufficiency threshold. It is not a
    claim that the page is satisfactorily resolved and remains eligible for future OCR policy.
    """

    EMBEDDED_TEXT = "embedded_text"
    SPARSE_EMBEDDED_TEXT = "sparse_embedded_text"
    OCR_CANDIDATE = "ocr_candidate"


class ExtractionMethod(StrEnum):
    """Method actually applied to one page."""

    PYPDF_EMBEDDED_TEXT = "pypdf_embedded_text"
    OCR_ROUTING_ONLY = "ocr_routing_only"


@dataclass(frozen=True, slots=True)
class ExtractionLimits:
    """Bounds on accepted extracted-text output, independent of ingestion limits."""

    max_characters_per_page: int = 2_000_000
    max_characters_per_document: int = 20_000_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_characters_per_page", self.max_characters_per_page),
            ("max_characters_per_document", self.max_characters_per_document),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_EXTRACTION_LIMITS = ExtractionLimits()


@dataclass(frozen=True, slots=True)
class TextExtractionConfig:
    """Small output-affecting configuration captured in artifact identity."""

    pdf_extraction_mode: PdfExtractionMode = PdfExtractionMode.PLAIN
    minimum_embedded_characters: int = 4
    limits: ExtractionLimits = DEFAULT_EXTRACTION_LIMITS

    def __post_init__(self) -> None:
        if not isinstance(self.pdf_extraction_mode, PdfExtractionMode):
            raise ValueError("pdf_extraction_mode must be a supported mode")
        if (
            isinstance(self.minimum_embedded_characters, bool)
            or self.minimum_embedded_characters < 1
        ):
            raise ValueError("minimum_embedded_characters must be a positive integer")
        if not isinstance(self.limits, ExtractionLimits):
            raise ValueError("limits must be an ExtractionLimits value")


DEFAULT_TEXT_EXTRACTION_CONFIG = TextExtractionConfig()


@dataclass(frozen=True, slots=True)
class ExtractorDescriptor:
    """Versioned identity of this stage and its PDF extraction backend."""

    name: str
    version: str
    pdf_backend_name: str
    pdf_backend_version: str

    def __post_init__(self) -> None:
        if self.name != EXTRACTOR_NAME:
            raise ValueError(f"extractor name must be {EXTRACTOR_NAME}")
        if not self.version:
            raise ValueError("extractor version must not be empty")
        if self.pdf_backend_name != PDF_BACKEND_NAME:
            raise ValueError(f"PDF backend name must be {PDF_BACKEND_NAME}")
        if not self.pdf_backend_version:
            raise ValueError("PDF backend version must not be empty")


@dataclass(frozen=True, slots=True)
class PageTextResult:
    """Faithful extracted text, statistics, and explicit routing for one page."""

    page_id: str
    page_number: int
    method: ExtractionMethod
    status: PageTextStatus
    text: str | None
    character_count: int
    non_whitespace_character_count: int

    def __post_init__(self) -> None:
        if isinstance(self.page_number, bool) or self.page_number < 1:
            raise ValueError("page_number must be a positive 1-based integer")
        if not isinstance(self.method, ExtractionMethod):
            raise ValueError("method must be a supported extraction method")
        if not isinstance(self.status, PageTextStatus):
            raise ValueError("status must be a supported page text status")
        if isinstance(self.character_count, bool) or self.character_count < 0:
            raise ValueError("character_count must be a non-negative integer")
        if (
            isinstance(self.non_whitespace_character_count, bool)
            or self.non_whitespace_character_count < 0
            or self.non_whitespace_character_count > self.character_count
        ):
            raise ValueError("non_whitespace_character_count is invalid")

        if self.text is None:
            if self.character_count != 0 or self.non_whitespace_character_count != 0:
                raise ValueError("absent text must have zero character counts")
        else:
            if self.character_count != len(self.text):
                raise ValueError("character_count does not match text")
            if self.non_whitespace_character_count != sum(
                not character.isspace() for character in self.text
            ):
                raise ValueError("non_whitespace_character_count does not match text")

        if self.status is PageTextStatus.OCR_CANDIDATE and self.text is not None:
            raise ValueError("OCR-candidate pages must not claim extracted text")
        if self.status is not PageTextStatus.OCR_CANDIDATE and self.text is None:
            raise ValueError("embedded-text pages must retain extracted text")
        if (
            self.method is ExtractionMethod.OCR_ROUTING_ONLY
            and self.status is not PageTextStatus.OCR_CANDIDATE
        ):
            raise ValueError("routing-only pages must be OCR candidates")


@dataclass(frozen=True, slots=True)
class TextExtractionArtifact:
    """Canonical derived text artifact linked to one immutable document."""

    schema_version: int
    artifact_id: str
    document_id: str
    document_fingerprint: str
    extractor: ExtractorDescriptor
    configuration: TextExtractionConfig
    page_count: int
    content_fingerprint: str
    pages: tuple[PageTextResult, ...]

    def __post_init__(self) -> None:
        if self.schema_version != EXTRACTION_SCHEMA_VERSION:
            raise ValueError(f"unsupported extraction schema version: {self.schema_version}")
        if not is_extraction_id(self.artifact_id):
            raise ValueError("artifact_id is not a canonical text artifact identifier")
        if not is_sha256(self.document_fingerprint):
            raise ValueError("document_fingerprint must be a canonical SHA-256 digest")
        if self.document_id != document_id_for(self.document_fingerprint):
            raise ValueError("document_id does not match document_fingerprint")
        if self.artifact_id != artifact_id_for(
            self.document_fingerprint, self.extractor, self.configuration
        ):
            raise ValueError("artifact_id does not match extraction inputs")
        if not isinstance(self.pages, tuple):
            raise ValueError("pages must be an immutable tuple")
        if self.page_count != len(self.pages) or self.page_count < 1:
            raise ValueError("page_count must match a non-empty page collection")
        if not is_sha256(self.content_fingerprint):
            raise ValueError("content_fingerprint must be a canonical SHA-256 digest")
        if self.content_fingerprint != content_fingerprint_for(self.pages):
            raise ValueError("content_fingerprint does not match page results")

        threshold = self.configuration.minimum_embedded_characters
        for expected_number, page in enumerate(self.pages, start=1):
            if page.page_number != expected_number:
                raise ValueError("pages must use contiguous 1-based numbering")
            if page.page_id != page_id_for(self.document_id, expected_number):
                raise ValueError("page_id does not match document_id and page_number")
            count = page.non_whitespace_character_count
            if page.status is PageTextStatus.OCR_CANDIDATE and count != 0:
                raise ValueError("OCR-candidate pages must have no usable embedded text")
            if page.status is PageTextStatus.SPARSE_EMBEDDED_TEXT and not 0 < count < threshold:
                raise ValueError("sparse text must be below the configured embedded-text threshold")
            if page.status is PageTextStatus.EMBEDDED_TEXT and count < threshold:
                raise ValueError("embedded text must meet the configured character threshold")


def is_extraction_id(value: str) -> bool:
    """Return whether *value* is a path-safe text artifact identifier."""

    return _ARTIFACT_ID_PATTERN.fullmatch(value) is not None


def artifact_id_for(
    document_fingerprint: str,
    extractor: ExtractorDescriptor,
    configuration: TextExtractionConfig,
) -> str:
    """Derive identity only from the source and output-affecting extraction inputs."""

    if not is_sha256(document_fingerprint):
        raise ValueError("document_fingerprint must be a canonical SHA-256 digest")
    payload = {
        "configuration": {
            "limits": {
                "max_characters_per_document": (configuration.limits.max_characters_per_document),
                "max_characters_per_page": configuration.limits.max_characters_per_page,
            },
            "minimum_embedded_characters": configuration.minimum_embedded_characters,
            "pdf_extraction_mode": configuration.pdf_extraction_mode.value,
        },
        "document_fingerprint": document_fingerprint,
        "extractor": {
            "name": extractor.name,
            "pdf_backend_name": extractor.pdf_backend_name,
            "pdf_backend_version": extractor.pdf_backend_version,
            "version": extractor.version,
        },
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "type": "pagetrace_text_extraction",
    }
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return f"text-sha256-{digest}"


def content_fingerprint_for(pages: tuple[PageTextResult, ...]) -> str:
    """Fingerprint canonical page results so accidental persisted corruption is detected."""

    payload = [
        {
            "character_count": page.character_count,
            "method": page.method.value,
            "non_whitespace_character_count": page.non_whitespace_character_count,
            "page_id": page.page_id,
            "page_number": page.page_number,
            "status": page.status.value,
            "text": page.text,
        }
        for page in pages
    ]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
