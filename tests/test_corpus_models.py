from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pagetrace.corpus import (
    DEFAULT_CORPUS_CONFIG,
    CorpusConfig,
    CorpusIntegrityError,
    CorpusLimitError,
    CorpusLimits,
    CorpusProcessorDescriptor,
    build_corpus_artifact,
    chunk_id_for,
    corpus_artifact_id_for,
    deserialize_corpus_artifact,
    is_chunk_id,
    is_corpus_artifact_id,
    serialize_corpus_artifact,
)
from pagetrace.documents import DimensionUnit
from pagetrace.documents.models import page_id_for
from pagetrace.structure import (
    BoundingBox,
    CoordinateOrigin,
    StructuredDocumentArtifact,
    StructuredPage,
    TextSpan,
    TextSpanSource,
    span_id_for,
    structure_content_fingerprint_for,
)
from tests.test_structure_models import _artifact as structure_artifact


def test_default_corpus_configuration_is_explicit_and_bounded() -> None:
    assert DEFAULT_CORPUS_CONFIG.max_characters_per_chunk == 4_000
    assert DEFAULT_CORPUS_CONFIG.embedded_word_separator == " "
    assert DEFAULT_CORPUS_CONFIG.line_separator == "\n"
    assert DEFAULT_CORPUS_CONFIG.limits.max_chunks_per_page == 10_000
    assert DEFAULT_CORPUS_CONFIG.limits.max_characters_per_document == 50_000_000


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"max_characters_per_chunk": 0}, "positive integer"),
        ({"max_characters_per_chunk": True}, "positive integer"),
        ({"embedded_word_separator": ""}, "non-empty"),
        ({"line_separator": "x" * 9}, "at most 8"),
        ({"line_separator": "\x00"}, "NUL"),
        ({"limits": "limits"}, "CorpusLimits"),
    ],
)
def test_corpus_configuration_rejects_invalid_values(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        CorpusConfig(**changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "max_chunks_per_page",
        "max_chunks_per_document",
        "max_fragments_per_chunk",
        "max_fragments_per_document",
        "max_characters_per_document",
    ],
)
def test_corpus_limits_require_positive_integers(field: str) -> None:
    values: dict[str, object] = {
        "max_chunks_per_page": 1,
        "max_chunks_per_document": 1,
        "max_fragments_per_chunk": 1,
        "max_fragments_per_document": 1,
        "max_characters_per_document": 1,
    }
    values[field] = 0
    with pytest.raises(ValueError, match="positive integer"):
        CorpusLimits(**values)  # type: ignore[arg-type]


def test_processor_descriptor_has_fixed_name_and_version() -> None:
    with pytest.raises(ValueError, match="processor name"):
        CorpusProcessorDescriptor(name="other")
    with pytest.raises(ValueError, match="version"):
        CorpusProcessorDescriptor(version="")


def test_chunking_is_page_bounded_deterministic_and_fully_reconstructable() -> None:
    source = _source((("abcdef", "ghij"), ("last",)))
    configuration = CorpusConfig(max_characters_per_chunk=5)

    artifact = build_corpus_artifact(source, configuration=configuration)
    replay = build_corpus_artifact(source, configuration=configuration)

    assert artifact == replay
    assert [chunk.text for chunk in artifact.chunks] == ["abcde", "f ghi", "j", "last"]
    assert [chunk.page_number for chunk in artifact.chunks] == [1, 1, 1, 2]
    assert [chunk.page_chunk_index for chunk in artifact.chunks] == [1, 2, 3, 1]
    assert all(chunk.character_count <= 5 for chunk in artifact.chunks)
    assert artifact.source_span_count == 3
    assert artifact.source_table_count == 0

    reconstructed: dict[tuple[int, int], str] = {}
    for chunk in artifact.chunks:
        assert chunk.page_id == source.pages[chunk.page_number - 1].page_id
        for fragment in chunk.fragments:
            key = (chunk.page_number, fragment.span_index)
            reconstructed[key] = (
                reconstructed.get(key, "") + chunk.text[fragment.chunk_start : fragment.chunk_end]
            )
    assert reconstructed == {(1, 1): "abcdef", (1, 2): "ghij", (2, 1): "last"}


def test_fragment_limit_flushes_chunks_without_losing_source_text() -> None:
    source = _source((("one", "two"),))
    limits = replace(DEFAULT_CORPUS_CONFIG.limits, max_fragments_per_chunk=1)
    artifact = build_corpus_artifact(
        source,
        configuration=CorpusConfig(max_characters_per_chunk=20, limits=limits),
    )

    assert [chunk.text for chunk in artifact.chunks] == ["one", "two"]
    assert all(len(chunk.fragments) == 1 for chunk in artifact.chunks)


def test_ocr_lines_use_newlines_while_embedded_words_use_spaces() -> None:
    source = _source((("embedded", "OCR line"),))
    page = source.pages[0]
    ocr_span = replace(
        page.spans[1],
        span_id=span_id_for(page.page_id, TextSpanSource.OCR_LINE, 2),
        source=TextSpanSource.OCR_LINE,
        confidence=0.9,
    )
    pages = (replace(page, spans=(page.spans[0], ocr_span)),)
    source = replace(
        source,
        content_fingerprint=structure_content_fingerprint_for(pages),
        pages=pages,
    )

    artifact = build_corpus_artifact(source)

    assert artifact.chunks[0].text == "embedded\nOCR line"


def test_empty_structured_pages_produce_a_valid_empty_corpus() -> None:
    source = _source(((),))
    artifact = build_corpus_artifact(source)

    assert artifact.chunk_count == 0
    assert artifact.character_count == 0
    assert artifact.chunks == ()


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        (CorpusLimits(max_chunks_per_page=1), "page 1.*chunk limit"),
        (CorpusLimits(max_chunks_per_document=1), "document.*chunk limit"),
        (CorpusLimits(max_fragments_per_document=1), "fragment limit"),
        (CorpusLimits(max_characters_per_document=5), "character limit"),
    ],
)
def test_chunking_enforces_resource_limits(limits: CorpusLimits, message: str) -> None:
    source = _source((("abcdef", "gh"),))
    with pytest.raises(CorpusLimitError, match=message):
        build_corpus_artifact(
            source,
            configuration=CorpusConfig(max_characters_per_chunk=4, limits=limits),
        )


def test_corpus_round_trips_canonical_json() -> None:
    artifact = build_corpus_artifact(_source((("PageTrace", "corpus"),)))
    data = serialize_corpus_artifact(artifact)

    assert deserialize_corpus_artifact(data) == artifact
    assert serialize_corpus_artifact(deserialize_corpus_artifact(data)) == data
    assert data.endswith(b"\n")


def test_identity_changes_with_source_configuration_and_processor() -> None:
    source = _source((("text",),))
    artifact = build_corpus_artifact(source)
    changed_config = corpus_artifact_id_for(
        source.document_fingerprint,
        source.artifact_id,
        source.content_fingerprint,
        artifact.processor,
        CorpusConfig(max_characters_per_chunk=10),
    )
    changed_processor = corpus_artifact_id_for(
        source.document_fingerprint,
        source.artifact_id,
        source.content_fingerprint,
        CorpusProcessorDescriptor(version="2"),
        DEFAULT_CORPUS_CONFIG,
    )

    assert is_corpus_artifact_id(artifact.artifact_id)
    assert is_chunk_id(artifact.chunks[0].chunk_id)
    assert len({artifact.artifact_id, changed_config, changed_processor}) == 3


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda artifact: replace(artifact, schema_version=2), "schema version"),
        (lambda artifact: replace(artifact, artifact_id="bad"), "artifact_id"),
        (lambda artifact: replace(artifact, document_fingerprint="bad"), "document_fingerprint"),
        (lambda artifact: replace(artifact, page_count=0), "page_count"),
        (lambda artifact: replace(artifact, chunks=[]), "immutable tuple"),
        (lambda artifact: replace(artifact, chunk_count=2), "chunk_count"),
        (lambda artifact: replace(artifact, character_count=0), "character_count"),
        (lambda artifact: replace(artifact, content_fingerprint="0" * 64), "fingerprint"),
    ],
)
def test_corpus_artifact_rejects_invalid_contract(mutation: object, message: str) -> None:
    artifact = build_corpus_artifact(_source((("text",),)))
    with pytest.raises(ValueError, match=message):
        mutation(artifact)  # type: ignore[operator]


def test_chunk_and_fragment_models_reject_contradictions() -> None:
    artifact = build_corpus_artifact(_source((("text",),)))
    chunk = artifact.chunks[0]
    fragment = chunk.fragments[0]

    with pytest.raises(ValueError, match="chunk_id"):
        replace(chunk, chunk_id="bad")
    with pytest.raises(ValueError, match="character_count"):
        replace(chunk, character_count=1)
    with pytest.raises(ValueError, match="chunk text"):
        replace(chunk, text="")
    with pytest.raises(ValueError, match="equal length"):
        replace(fragment, source_end=fragment.source_end + 1)
    with pytest.raises(ValueError, match="non-empty"):
        replace(fragment, source_end=fragment.source_start)
    with pytest.raises(ValueError, match="non-negative"):
        replace(fragment, source_start=-1)


def test_identifier_helpers_reject_invalid_inputs() -> None:
    source = _source((("text",),))
    artifact = build_corpus_artifact(source)
    with pytest.raises(ValueError, match="corpus_artifact_id"):
        chunk_id_for("bad", 1)
    with pytest.raises(ValueError, match="chunk_index"):
        chunk_id_for(artifact.artifact_id, 0)
    with pytest.raises(ValueError, match="document_fingerprint"):
        corpus_artifact_id_for(
            "bad",
            source.artifact_id,
            source.content_fingerprint,
            artifact.processor,
            artifact.configuration,
        )
    with pytest.raises(ValueError, match="source_structure_artifact_id"):
        corpus_artifact_id_for(
            source.document_fingerprint,
            "bad",
            source.content_fingerprint,
            artifact.processor,
            artifact.configuration,
        )


def test_deserializer_rejects_malformed_fields_and_types() -> None:
    artifact = build_corpus_artifact(_source((("text",),)))
    payload = json.loads(serialize_corpus_artifact(artifact))
    with pytest.raises(CorpusIntegrityError, match="UTF-8 JSON"):
        deserialize_corpus_artifact(b"not json")
    with pytest.raises(CorpusIntegrityError, match="fields are invalid"):
        deserialize_corpus_artifact(b"{}")

    payload["chunks"] = {}
    with pytest.raises(CorpusIntegrityError, match="JSON array"):
        deserialize_corpus_artifact(json.dumps(payload).encode())


def _source(texts_by_page: tuple[tuple[str, ...], ...]) -> StructuredDocumentArtifact:
    base = structure_artifact()
    pages: list[StructuredPage] = []
    for page_number, texts in enumerate(texts_by_page, start=1):
        page_id = page_id_for(base.document_id, page_number)
        spans = tuple(
            TextSpan(
                span_id=span_id_for(page_id, TextSpanSource.EMBEDDED_WORD, span_index),
                span_index=span_index,
                source=TextSpanSource.EMBEDDED_WORD,
                text=text,
                bounding_box=BoundingBox(10, 10 * span_index, 70, 10 * span_index + 8),
                confidence=None,
            )
            for span_index, text in enumerate(texts, start=1)
        )
        pages.append(
            StructuredPage(
                page_id=page_id,
                page_number=page_number,
                width=200,
                height=200,
                dimension_unit=DimensionUnit.POINTS,
                coordinate_origin=CoordinateOrigin.TOP_LEFT,
                source_rotation_degrees=0,
                spans=spans,
                tables=(),
            )
        )
    immutable_pages = tuple(pages)
    return replace(
        base,
        page_count=len(immutable_pages),
        span_count=sum(len(page.spans) for page in immutable_pages),
        table_count=0,
        cell_count=0,
        content_fingerprint=structure_content_fingerprint_for(immutable_pages),
        pages=immutable_pages,
    )
