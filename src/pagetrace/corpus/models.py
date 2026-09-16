"""Immutable models for deterministic, provenance-aware corpus chunks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from pagetrace.documents import DimensionUnit
from pagetrace.documents.models import document_id_for, is_sha256, page_id_for
from pagetrace.structure import BoundingBox, CoordinateOrigin, TextSpanSource
from pagetrace.structure.models import is_structure_artifact_id

CORPUS_SCHEMA_VERSION = 1
CORPUS_PROCESSOR_NAME = "pagetrace-corpus-builder"
CORPUS_PROCESSOR_VERSION = "1"
_CORPUS_ID_PATTERN = re.compile(r"^corpus-sha256-[0-9a-f]{64}$")
_CHUNK_ID_PATTERN = re.compile(r"^chunk-sha256-[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CorpusLimits:
    """Resource bounds for corpus construction and readback."""

    max_chunks_per_page: int = 10_000
    max_chunks_per_document: int = 100_000
    max_fragments_per_chunk: int = 10_000
    max_fragments_per_document: int = 1_000_000
    max_characters_per_document: int = 50_000_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_chunks_per_page", self.max_chunks_per_page),
            ("max_chunks_per_document", self.max_chunks_per_document),
            ("max_fragments_per_chunk", self.max_fragments_per_chunk),
            ("max_fragments_per_document", self.max_fragments_per_document),
            ("max_characters_per_document", self.max_characters_per_document),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_CORPUS_LIMITS = CorpusLimits()


@dataclass(frozen=True, slots=True)
class CorpusConfig:
    """Output-affecting chunk size, separator, and resource limits."""

    max_characters_per_chunk: int = 4_000
    embedded_word_separator: str = " "
    line_separator: str = "\n"
    limits: CorpusLimits = DEFAULT_CORPUS_LIMITS

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_characters_per_chunk, bool)
            or not isinstance(self.max_characters_per_chunk, int)
            or self.max_characters_per_chunk <= 0
        ):
            raise ValueError("max_characters_per_chunk must be a positive integer")
        for name, separator in (
            ("embedded_word_separator", self.embedded_word_separator),
            ("line_separator", self.line_separator),
        ):
            if not isinstance(separator, str) or not separator:
                raise ValueError(f"{name} must be a non-empty string")
            if len(separator) > 8 or "\x00" in separator:
                raise ValueError(f"{name} must be at most 8 characters and contain no NUL")
        if not isinstance(self.limits, CorpusLimits):
            raise ValueError("limits must be a CorpusLimits value")


DEFAULT_CORPUS_CONFIG = CorpusConfig()


@dataclass(frozen=True, slots=True)
class CorpusProcessorDescriptor:
    """Versioned identity of the deterministic corpus builder."""

    name: str = CORPUS_PROCESSOR_NAME
    version: str = CORPUS_PROCESSOR_VERSION

    def __post_init__(self) -> None:
        if self.name != CORPUS_PROCESSOR_NAME:
            raise ValueError(f"corpus processor name must be {CORPUS_PROCESSOR_NAME}")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("corpus processor version must not be empty")


DEFAULT_CORPUS_PROCESSOR = CorpusProcessorDescriptor()


@dataclass(frozen=True, slots=True)
class ChunkFragment:
    """Exact character slice of one positioned structured text span."""

    fragment_index: int
    span_id: str
    span_index: int
    source: TextSpanSource
    source_start: int
    source_end: int
    chunk_start: int
    chunk_end: int
    bounding_box: BoundingBox

    def __post_init__(self) -> None:
        for name, value in (
            ("fragment_index", self.fragment_index),
            ("span_index", self.span_index),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive 1-based integer")
        if not isinstance(self.span_id, str) or not self.span_id:
            raise ValueError("span_id must not be empty")
        if not isinstance(self.source, TextSpanSource):
            raise ValueError("source must be a supported text span source")
        for name, value in (
            ("source_start", self.source_start),
            ("source_end", self.source_end),
            ("chunk_start", self.chunk_start),
            ("chunk_end", self.chunk_end),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.source_end <= self.source_start or self.chunk_end <= self.chunk_start:
            raise ValueError("fragment source and chunk ranges must be non-empty")
        if self.source_end - self.source_start != self.chunk_end - self.chunk_start:
            raise ValueError("fragment source and chunk ranges must have equal length")
        if not isinstance(self.bounding_box, BoundingBox):
            raise ValueError("bounding_box must be a BoundingBox")


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """One page-bounded text chunk with exact region and source slices."""

    chunk_id: str
    chunk_index: int
    page_chunk_index: int
    page_id: str
    page_number: int
    dimension_unit: DimensionUnit
    coordinate_origin: CoordinateOrigin
    bounding_box: BoundingBox
    text: str
    character_count: int
    content_fingerprint: str
    fragments: tuple[ChunkFragment, ...]

    def __post_init__(self) -> None:
        if not is_chunk_id(self.chunk_id):
            raise ValueError("chunk_id is not a canonical chunk identifier")
        for name, value in (
            ("chunk_index", self.chunk_index),
            ("page_chunk_index", self.page_chunk_index),
            ("page_number", self.page_number),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive 1-based integer")
        if not isinstance(self.dimension_unit, DimensionUnit):
            raise ValueError("dimension_unit must be points or pixels")
        if self.coordinate_origin is not CoordinateOrigin.TOP_LEFT:
            raise ValueError("coordinate_origin must be top_left")
        if not isinstance(self.bounding_box, BoundingBox):
            raise ValueError("bounding_box must be a BoundingBox")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("chunk text must not be empty")
        if self.character_count != len(self.text):
            raise ValueError("character_count must match chunk text")
        if self.content_fingerprint != text_fingerprint_for(self.text):
            raise ValueError("content_fingerprint must match chunk text")
        if not isinstance(self.fragments, tuple) or not self.fragments:
            raise ValueError("fragments must be a non-empty immutable tuple")
        previous_end = 0
        boxes: list[BoundingBox] = []
        for expected_index, fragment in enumerate(self.fragments, start=1):
            if fragment.fragment_index != expected_index:
                raise ValueError("fragments must use contiguous 1-based order")
            if fragment.chunk_start < previous_end or fragment.chunk_end > len(self.text):
                raise ValueError("fragment chunk ranges must be ordered inside chunk text")
            previous_end = fragment.chunk_end
            boxes.append(fragment.bounding_box)
        if self.bounding_box != bounding_box_union(boxes):
            raise ValueError("chunk bounding_box must cover all fragment regions")


@dataclass(frozen=True, slots=True)
class CorpusArtifact:
    """Canonical per-document corpus linked to one exact structured artifact."""

    schema_version: int
    artifact_id: str
    document_id: str
    document_fingerprint: str
    source_structure_artifact_id: str
    source_structure_content_fingerprint: str
    processor: CorpusProcessorDescriptor
    configuration: CorpusConfig
    page_count: int
    source_span_count: int
    source_table_count: int
    chunk_count: int
    character_count: int
    content_fingerprint: str
    chunks: tuple[ChunkRecord, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CORPUS_SCHEMA_VERSION:
            raise ValueError(f"unsupported corpus schema version: {self.schema_version}")
        if not is_corpus_artifact_id(self.artifact_id):
            raise ValueError("artifact_id is not a canonical corpus identifier")
        if not is_sha256(self.document_fingerprint):
            raise ValueError("document_fingerprint must be a canonical SHA-256 digest")
        if self.document_id != document_id_for(self.document_fingerprint):
            raise ValueError("document_id does not match document_fingerprint")
        if not is_structure_artifact_id(self.source_structure_artifact_id):
            raise ValueError("source_structure_artifact_id is not canonical")
        if not is_sha256(self.source_structure_content_fingerprint):
            raise ValueError("source_structure_content_fingerprint must be a SHA-256 digest")
        if self.artifact_id != corpus_artifact_id_for(
            self.document_fingerprint,
            self.source_structure_artifact_id,
            self.source_structure_content_fingerprint,
            self.processor,
            self.configuration,
        ):
            raise ValueError("artifact_id does not match corpus inputs")
        if (
            isinstance(self.page_count, bool)
            or not isinstance(self.page_count, int)
            or self.page_count < 1
        ):
            raise ValueError("page_count must be a positive integer")
        for name, value in (
            ("source_span_count", self.source_span_count),
            ("source_table_count", self.source_table_count),
            ("chunk_count", self.chunk_count),
            ("character_count", self.character_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.chunks, tuple):
            raise ValueError("chunks must be an immutable tuple")
        if self.chunk_count != len(self.chunks):
            raise ValueError("chunk_count must match chunks")
        if self.character_count != sum(chunk.character_count for chunk in self.chunks):
            raise ValueError("character_count must match chunks")
        if self.content_fingerprint != corpus_content_fingerprint_for(self.chunks):
            raise ValueError("content_fingerprint must match chunks")
        limits = self.configuration.limits
        if self.chunk_count > limits.max_chunks_per_document:
            raise ValueError("corpus exceeds the document chunk limit")
        if self.character_count > limits.max_characters_per_document:
            raise ValueError("corpus exceeds the document character limit")
        if sum(len(chunk.fragments) for chunk in self.chunks) > limits.max_fragments_per_document:
            raise ValueError("corpus exceeds the document fragment limit")
        page_counts: dict[int, int] = {}
        page_chunk_counts: dict[int, int] = {}
        for expected_index, chunk in enumerate(self.chunks, start=1):
            if chunk.chunk_index != expected_index:
                raise ValueError("chunks must use contiguous 1-based order")
            if chunk.chunk_id != chunk_id_for(self.artifact_id, expected_index):
                raise ValueError("chunk_id does not match corpus and order")
            if chunk.page_number > self.page_count:
                raise ValueError("chunk page_number exceeds page_count")
            if chunk.page_id != page_id_for(self.document_id, chunk.page_number):
                raise ValueError("chunk page_id does not match document and page number")
            expected_page_index = page_counts.get(chunk.page_number, 0) + 1
            if chunk.page_chunk_index != expected_page_index:
                raise ValueError("page chunks must use contiguous 1-based order")
            page_counts[chunk.page_number] = expected_page_index
            page_chunk_counts[chunk.page_number] = expected_page_index
            if chunk.character_count > self.configuration.max_characters_per_chunk:
                raise ValueError("chunk exceeds max_characters_per_chunk")
            if len(chunk.fragments) > limits.max_fragments_per_chunk:
                raise ValueError("chunk exceeds the fragment limit")
        if any(count > limits.max_chunks_per_page for count in page_chunk_counts.values()):
            raise ValueError("corpus page exceeds the chunk limit")


def is_corpus_artifact_id(value: str) -> bool:
    return isinstance(value, str) and _CORPUS_ID_PATTERN.fullmatch(value) is not None


def is_chunk_id(value: str) -> bool:
    return isinstance(value, str) and _CHUNK_ID_PATTERN.fullmatch(value) is not None


def chunk_id_for(corpus_artifact_id: str, chunk_index: int) -> str:
    if not is_corpus_artifact_id(corpus_artifact_id):
        raise ValueError("corpus_artifact_id must be canonical")
    if isinstance(chunk_index, bool) or not isinstance(chunk_index, int) or chunk_index < 1:
        raise ValueError("chunk_index must be a positive 1-based integer")
    data = f"{corpus_artifact_id}:{chunk_index}".encode()
    return f"chunk-sha256-{hashlib.sha256(data).hexdigest()}"


def corpus_artifact_id_for(
    document_fingerprint: str,
    source_structure_artifact_id: str,
    source_structure_content_fingerprint: str,
    processor: CorpusProcessorDescriptor,
    configuration: CorpusConfig,
) -> str:
    if not is_sha256(document_fingerprint):
        raise ValueError("document_fingerprint must be a canonical SHA-256 digest")
    if not is_structure_artifact_id(source_structure_artifact_id):
        raise ValueError("source_structure_artifact_id must be canonical")
    if not is_sha256(source_structure_content_fingerprint):
        raise ValueError("source_structure_content_fingerprint must be a SHA-256 digest")
    payload = {
        "configuration": configuration_payload(configuration),
        "document_fingerprint": document_fingerprint,
        "processor": {"name": processor.name, "version": processor.version},
        "schema_version": CORPUS_SCHEMA_VERSION,
        "source_structure_artifact_id": source_structure_artifact_id,
        "source_structure_content_fingerprint": source_structure_content_fingerprint,
        "type": "pagetrace_corpus",
    }
    return f"corpus-sha256-{hashlib.sha256(canonical_json(payload)).hexdigest()}"


def corpus_content_fingerprint_for(chunks: tuple[ChunkRecord, ...]) -> str:
    return hashlib.sha256(canonical_json([chunk_payload(chunk) for chunk in chunks])).hexdigest()


def text_fingerprint_for(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def bounding_box_union(boxes: list[BoundingBox]) -> BoundingBox:
    if not boxes:
        raise ValueError("at least one bounding box is required")
    return BoundingBox(
        min(box.x0 for box in boxes),
        min(box.top for box in boxes),
        max(box.x1 for box in boxes),
        max(box.bottom for box in boxes),
    )


def configuration_payload(configuration: CorpusConfig) -> dict[str, object]:
    limits = configuration.limits
    return {
        "limits": {
            "max_characters_per_document": limits.max_characters_per_document,
            "max_chunks_per_document": limits.max_chunks_per_document,
            "max_chunks_per_page": limits.max_chunks_per_page,
            "max_fragments_per_chunk": limits.max_fragments_per_chunk,
            "max_fragments_per_document": limits.max_fragments_per_document,
        },
        "embedded_word_separator": configuration.embedded_word_separator,
        "line_separator": configuration.line_separator,
        "max_characters_per_chunk": configuration.max_characters_per_chunk,
    }


def chunk_payload(chunk: ChunkRecord) -> dict[str, object]:
    return {
        "bounding_box": box_payload(chunk.bounding_box),
        "character_count": chunk.character_count,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "content_fingerprint": chunk.content_fingerprint,
        "coordinate_origin": chunk.coordinate_origin.value,
        "dimension_unit": chunk.dimension_unit.value,
        "fragments": [
            {
                "bounding_box": box_payload(fragment.bounding_box),
                "chunk_end": fragment.chunk_end,
                "chunk_start": fragment.chunk_start,
                "fragment_index": fragment.fragment_index,
                "source": fragment.source.value,
                "source_end": fragment.source_end,
                "source_start": fragment.source_start,
                "span_id": fragment.span_id,
                "span_index": fragment.span_index,
            }
            for fragment in chunk.fragments
        ],
        "page_chunk_index": chunk.page_chunk_index,
        "page_id": chunk.page_id,
        "page_number": chunk.page_number,
        "text": chunk.text,
    }


def box_payload(box: BoundingBox) -> dict[str, float]:
    return {
        "bottom": float(box.bottom),
        "top": float(box.top),
        "x0": float(box.x0),
        "x1": float(box.x1),
    }


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
