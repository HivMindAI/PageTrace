"""Immutable values used by the document ingestion boundary."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

SCHEMA_VERSION = 1
SHA256_ALGORITHM = "sha256"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DOCUMENT_ID_PATTERN = re.compile(r"^sha256-[0-9a-f]{64}$")


class MediaType(StrEnum):
    """Supported content-derived media types."""

    PDF = "application/pdf"
    PNG = "image/png"
    JPEG = "image/jpeg"


class DimensionUnit(StrEnum):
    """Unit used for page dimensions."""

    POINTS = "points"
    PIXELS = "pixels"


@dataclass(frozen=True, slots=True)
class IngestionLimits:
    """Configurable bounds applied while ingesting untrusted documents."""

    max_file_bytes: int = 100 * 1024 * 1024
    max_pdf_pages: int = 2_000
    max_image_pixels: int = 100_000_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_file_bytes", self.max_file_bytes),
            ("max_pdf_pages", self.max_pdf_pages),
            ("max_image_pixels", self.max_image_pixels),
        ):
            if isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_INGESTION_LIMITS = IngestionLimits()


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    """Small, explicit whitelist of embedded PDF metadata."""

    title: str | None = None
    author: str | None = None
    subject: str | None = None
    creator: str | None = None
    producer: str | None = None
    creation_date: str | None = None
    modification_date: str | None = None


@dataclass(frozen=True, slots=True)
class PageManifest:
    """Deterministic description of one user-facing document page."""

    page_id: str
    page_number: int
    width: int | float
    height: int | float
    dimension_unit: DimensionUnit
    rotation_degrees: int | None

    def __post_init__(self) -> None:
        if isinstance(self.page_number, bool) or self.page_number < 1:
            raise ValueError("page_number must be a positive 1-based integer")
        for name, value in (("width", self.width), ("height", self.height)):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if self.rotation_degrees not in (None, 0, 90, 180, 270):
            raise ValueError("rotation_degrees must be null, 0, 90, 180, or 270")


@dataclass(frozen=True, slots=True)
class DocumentManifest:
    """Canonical, content-derived immutable document artifact manifest."""

    schema_version: int
    document_id: str
    fingerprint_algorithm: str
    fingerprint: str
    media_type: MediaType
    byte_size: int
    page_count: int
    document_metadata: DocumentMetadata
    pages: tuple[PageManifest, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema version: {self.schema_version}")
        if self.fingerprint_algorithm != SHA256_ALGORITHM:
            raise ValueError("fingerprint_algorithm must be sha256")
        if not is_sha256(self.fingerprint):
            raise ValueError("fingerprint must be 64 lowercase hexadecimal characters")
        if self.document_id != document_id_for(self.fingerprint):
            raise ValueError("document_id does not match the content fingerprint")
        if isinstance(self.byte_size, bool) or self.byte_size <= 0:
            raise ValueError("byte_size must be a positive integer")
        if not isinstance(self.pages, tuple):
            raise ValueError("pages must be an immutable tuple")
        if self.page_count != len(self.pages) or self.page_count < 1:
            raise ValueError("page_count must match a non-empty page collection")

        expected_unit = (
            DimensionUnit.POINTS if self.media_type is MediaType.PDF else DimensionUnit.PIXELS
        )
        for expected_number, page in enumerate(self.pages, start=1):
            if page.page_number != expected_number:
                raise ValueError("pages must use contiguous 1-based numbering")
            if page.page_id != page_id_for(self.document_id, expected_number):
                raise ValueError("page_id does not match document_id and page_number")
            if page.dimension_unit is not expected_unit:
                raise ValueError("page dimension unit does not match document media type")
            if self.media_type is not MediaType.PDF and page.rotation_degrees is not None:
                raise ValueError("image pages must not declare PDF rotation")
        if self.media_type is not MediaType.PDF and self.page_count != 1:
            raise ValueError("image documents must contain exactly one page")


def is_sha256(value: str) -> bool:
    """Return whether *value* is a canonical full SHA-256 hex digest."""

    return _SHA256_PATTERN.fullmatch(value) is not None


def is_document_id(value: str) -> bool:
    """Return whether *value* is a path-safe PageTrace document identifier."""

    return _DOCUMENT_ID_PATTERN.fullmatch(value) is not None


def document_id_for(fingerprint: str) -> str:
    """Build the canonical path-safe document identity for a SHA-256 digest."""

    if not is_sha256(fingerprint):
        raise ValueError("fingerprint must be 64 lowercase hexadecimal characters")
    return f"sha256-{fingerprint}"


def page_id_for(document_id: str, page_number: int) -> str:
    """Build a stable page identity using a 1-based page number."""

    if not is_document_id(document_id):
        raise ValueError("invalid document_id")
    if isinstance(page_number, bool) or page_number < 1:
        raise ValueError("page_number must be a positive 1-based integer")
    return f"{document_id}-page-{page_number:06d}"
