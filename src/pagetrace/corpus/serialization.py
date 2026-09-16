"""Strict canonical JSON for provenance-aware corpus artifacts."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import cast

from pagetrace.corpus.errors import CorpusIntegrityError
from pagetrace.corpus.models import (
    ChunkFragment,
    ChunkRecord,
    CorpusArtifact,
    CorpusConfig,
    CorpusLimits,
    CorpusProcessorDescriptor,
    chunk_payload,
)
from pagetrace.documents import DimensionUnit
from pagetrace.structure import BoundingBox, CoordinateOrigin, TextSpanSource

_ARTIFACT_FIELDS = {
    "schema_version",
    "artifact_id",
    "document_id",
    "document_fingerprint",
    "source_structure_artifact_id",
    "source_structure_content_fingerprint",
    "processor",
    "configuration",
    "page_count",
    "source_span_count",
    "source_table_count",
    "chunk_count",
    "character_count",
    "content_fingerprint",
    "chunks",
}
_PROCESSOR_FIELDS = {"name", "version"}
_CONFIG_FIELDS = {
    "embedded_word_separator",
    "line_separator",
    "max_characters_per_chunk",
    "limits",
}
_LIMIT_FIELDS = {
    "max_chunks_per_page",
    "max_chunks_per_document",
    "max_fragments_per_chunk",
    "max_fragments_per_document",
    "max_characters_per_document",
}
_CHUNK_FIELDS = {
    "chunk_id",
    "chunk_index",
    "page_chunk_index",
    "page_id",
    "page_number",
    "dimension_unit",
    "coordinate_origin",
    "bounding_box",
    "text",
    "character_count",
    "content_fingerprint",
    "fragments",
}
_FRAGMENT_FIELDS = {
    "fragment_index",
    "span_id",
    "span_index",
    "source",
    "source_start",
    "source_end",
    "chunk_start",
    "chunk_end",
    "bounding_box",
}
_BOX_FIELDS = {"x0", "top", "x1", "bottom"}


def serialize_corpus_artifact(artifact: CorpusArtifact) -> bytes:
    """Serialize one validated corpus artifact as canonical UTF-8 JSON."""

    limits = artifact.configuration.limits
    payload: dict[str, object] = {
        "artifact_id": artifact.artifact_id,
        "character_count": artifact.character_count,
        "chunk_count": artifact.chunk_count,
        "chunks": [chunk_payload(chunk) for chunk in artifact.chunks],
        "configuration": {
            "embedded_word_separator": artifact.configuration.embedded_word_separator,
            "line_separator": artifact.configuration.line_separator,
            "limits": {
                "max_characters_per_document": limits.max_characters_per_document,
                "max_chunks_per_document": limits.max_chunks_per_document,
                "max_chunks_per_page": limits.max_chunks_per_page,
                "max_fragments_per_chunk": limits.max_fragments_per_chunk,
                "max_fragments_per_document": limits.max_fragments_per_document,
            },
            "max_characters_per_chunk": artifact.configuration.max_characters_per_chunk,
        },
        "content_fingerprint": artifact.content_fingerprint,
        "document_fingerprint": artifact.document_fingerprint,
        "document_id": artifact.document_id,
        "page_count": artifact.page_count,
        "processor": {"name": artifact.processor.name, "version": artifact.processor.version},
        "schema_version": artifact.schema_version,
        "source_span_count": artifact.source_span_count,
        "source_structure_artifact_id": artifact.source_structure_artifact_id,
        "source_structure_content_fingerprint": artifact.source_structure_content_fingerprint,
        "source_table_count": artifact.source_table_count,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{text}\n".encode()


def deserialize_corpus_artifact(data: bytes) -> CorpusArtifact:
    """Parse and fully validate strict corpus-artifact JSON."""

    try:
        value: object = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusIntegrityError("corpus artifact is not valid UTF-8 JSON") from exc
    artifact = _mapping(value, "corpus artifact")
    _exact(artifact, _ARTIFACT_FIELDS, "corpus artifact")
    processor_value = _mapping(artifact["processor"], "processor")
    _exact(processor_value, _PROCESSOR_FIELDS, "processor")
    config_value = _mapping(artifact["configuration"], "configuration")
    _exact(config_value, _CONFIG_FIELDS, "configuration")
    limits_value = _mapping(config_value["limits"], "configuration.limits")
    _exact(limits_value, _LIMIT_FIELDS, "configuration.limits")
    try:
        processor = CorpusProcessorDescriptor(
            name=_string(processor_value["name"], "processor.name"),
            version=_string(processor_value["version"], "processor.version"),
        )
        limits = CorpusLimits(
            max_chunks_per_page=_integer(
                limits_value["max_chunks_per_page"], "max_chunks_per_page"
            ),
            max_chunks_per_document=_integer(
                limits_value["max_chunks_per_document"], "max_chunks_per_document"
            ),
            max_fragments_per_chunk=_integer(
                limits_value["max_fragments_per_chunk"], "max_fragments_per_chunk"
            ),
            max_fragments_per_document=_integer(
                limits_value["max_fragments_per_document"], "max_fragments_per_document"
            ),
            max_characters_per_document=_integer(
                limits_value["max_characters_per_document"], "max_characters_per_document"
            ),
        )
        configuration = CorpusConfig(
            max_characters_per_chunk=_integer(
                config_value["max_characters_per_chunk"], "max_characters_per_chunk"
            ),
            embedded_word_separator=_string(
                config_value["embedded_word_separator"], "embedded_word_separator"
            ),
            line_separator=_string(config_value["line_separator"], "line_separator"),
            limits=limits,
        )
        chunks = tuple(_parse_chunk(item) for item in _array(artifact["chunks"], "chunks"))
        return CorpusArtifact(
            schema_version=_integer(artifact["schema_version"], "schema_version"),
            artifact_id=_string(artifact["artifact_id"], "artifact_id"),
            document_id=_string(artifact["document_id"], "document_id"),
            document_fingerprint=_string(artifact["document_fingerprint"], "document_fingerprint"),
            source_structure_artifact_id=_string(
                artifact["source_structure_artifact_id"], "source_structure_artifact_id"
            ),
            source_structure_content_fingerprint=_string(
                artifact["source_structure_content_fingerprint"],
                "source_structure_content_fingerprint",
            ),
            processor=processor,
            configuration=configuration,
            page_count=_integer(artifact["page_count"], "page_count"),
            source_span_count=_integer(artifact["source_span_count"], "source_span_count"),
            source_table_count=_integer(artifact["source_table_count"], "source_table_count"),
            chunk_count=_integer(artifact["chunk_count"], "chunk_count"),
            character_count=_integer(artifact["character_count"], "character_count"),
            content_fingerprint=_string(artifact["content_fingerprint"], "content_fingerprint"),
            chunks=chunks,
        )
    except (TypeError, ValueError) as exc:
        raise CorpusIntegrityError(f"invalid corpus artifact value: {exc}") from exc


def _parse_chunk(value: object) -> ChunkRecord:
    chunk = _mapping(value, "chunk")
    _exact(chunk, _CHUNK_FIELDS, "chunk")
    return ChunkRecord(
        chunk_id=_string(chunk["chunk_id"], "chunk.chunk_id"),
        chunk_index=_integer(chunk["chunk_index"], "chunk.chunk_index"),
        page_chunk_index=_integer(chunk["page_chunk_index"], "chunk.page_chunk_index"),
        page_id=_string(chunk["page_id"], "chunk.page_id"),
        page_number=_integer(chunk["page_number"], "chunk.page_number"),
        dimension_unit=DimensionUnit(_string(chunk["dimension_unit"], "chunk.dimension_unit")),
        coordinate_origin=CoordinateOrigin(
            _string(chunk["coordinate_origin"], "chunk.coordinate_origin")
        ),
        bounding_box=_parse_box(chunk["bounding_box"], "chunk.bounding_box"),
        text=_string(chunk["text"], "chunk.text"),
        character_count=_integer(chunk["character_count"], "chunk.character_count"),
        content_fingerprint=_string(chunk["content_fingerprint"], "chunk.content_fingerprint"),
        fragments=tuple(
            _parse_fragment(item) for item in _array(chunk["fragments"], "chunk.fragments")
        ),
    )


def _parse_fragment(value: object) -> ChunkFragment:
    fragment = _mapping(value, "fragment")
    _exact(fragment, _FRAGMENT_FIELDS, "fragment")
    return ChunkFragment(
        fragment_index=_integer(fragment["fragment_index"], "fragment.fragment_index"),
        span_id=_string(fragment["span_id"], "fragment.span_id"),
        span_index=_integer(fragment["span_index"], "fragment.span_index"),
        source=TextSpanSource(_string(fragment["source"], "fragment.source")),
        source_start=_integer(fragment["source_start"], "fragment.source_start"),
        source_end=_integer(fragment["source_end"], "fragment.source_end"),
        chunk_start=_integer(fragment["chunk_start"], "fragment.chunk_start"),
        chunk_end=_integer(fragment["chunk_end"], "fragment.chunk_end"),
        bounding_box=_parse_box(fragment["bounding_box"], "fragment.bounding_box"),
    )


def _parse_box(value: object, name: str) -> BoundingBox:
    box = _mapping(value, name)
    _exact(box, _BOX_FIELDS, name)
    return BoundingBox(
        x0=_number(box["x0"], f"{name}.x0"),
        top=_number(box["top"], f"{name}.top"),
        x1=_number(box["x1"], f"{name}.x1"),
        bottom=_number(box["bottom"], f"{name}.bottom"),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CorpusIntegrityError(f"{name} must be a JSON object with string keys")
    return cast(dict[str, object], value)


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise CorpusIntegrityError(f"{name} must be a JSON array")
    return value


def _exact(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise CorpusIntegrityError(
            f"{name} fields are invalid; missing={sorted(expected - set(value))}, "
            f"unexpected={sorted(set(value) - expected)}"
        )


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise CorpusIntegrityError(f"{name} must be a string")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CorpusIntegrityError(f"{name} must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CorpusIntegrityError(f"{name} must be a finite number")
    return float(value)
