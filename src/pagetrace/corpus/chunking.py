"""Pure deterministic chunk construction from verified structured documents."""

from __future__ import annotations

from pagetrace.corpus.errors import CorpusLimitError
from pagetrace.corpus.models import (
    CORPUS_SCHEMA_VERSION,
    DEFAULT_CORPUS_CONFIG,
    DEFAULT_CORPUS_PROCESSOR,
    ChunkFragment,
    ChunkRecord,
    CorpusArtifact,
    CorpusConfig,
    CorpusProcessorDescriptor,
    bounding_box_union,
    chunk_id_for,
    corpus_artifact_id_for,
    corpus_content_fingerprint_for,
    text_fingerprint_for,
)
from pagetrace.structure import StructuredDocumentArtifact, StructuredPage, TextSpanSource


def build_corpus_artifact(
    source: StructuredDocumentArtifact,
    *,
    configuration: CorpusConfig = DEFAULT_CORPUS_CONFIG,
    processor: CorpusProcessorDescriptor = DEFAULT_CORPUS_PROCESSOR,
) -> CorpusArtifact:
    """Build an immutable corpus in page and structured-span order."""

    if not isinstance(source, StructuredDocumentArtifact):
        raise ValueError("source must be a StructuredDocumentArtifact")
    if not isinstance(configuration, CorpusConfig):
        raise ValueError("configuration must be a CorpusConfig")
    if not isinstance(processor, CorpusProcessorDescriptor):
        raise ValueError("processor must be a CorpusProcessorDescriptor")

    artifact_id = corpus_artifact_id_for(
        source.document_fingerprint,
        source.artifact_id,
        source.content_fingerprint,
        processor,
        configuration,
    )
    chunks: list[ChunkRecord] = []
    fragment_count = 0
    character_count = 0
    for page in source.pages:
        page_chunks = _chunk_page(
            page,
            artifact_id=artifact_id,
            first_chunk_index=len(chunks) + 1,
            configuration=configuration,
        )
        chunks.extend(page_chunks)
        fragment_count += sum(len(chunk.fragments) for chunk in page_chunks)
        character_count += sum(chunk.character_count for chunk in page_chunks)
        limits = configuration.limits
        if len(chunks) > limits.max_chunks_per_document:
            raise CorpusLimitError("document exceeds the corpus chunk limit")
        if fragment_count > limits.max_fragments_per_document:
            raise CorpusLimitError("document exceeds the corpus fragment limit")
        if character_count > limits.max_characters_per_document:
            raise CorpusLimitError("document exceeds the corpus character limit")

    immutable_chunks = tuple(chunks)
    return CorpusArtifact(
        schema_version=CORPUS_SCHEMA_VERSION,
        artifact_id=artifact_id,
        document_id=source.document_id,
        document_fingerprint=source.document_fingerprint,
        source_structure_artifact_id=source.artifact_id,
        source_structure_content_fingerprint=source.content_fingerprint,
        processor=processor,
        configuration=configuration,
        page_count=source.page_count,
        source_span_count=source.span_count,
        source_table_count=source.table_count,
        chunk_count=len(immutable_chunks),
        character_count=character_count,
        content_fingerprint=corpus_content_fingerprint_for(immutable_chunks),
        chunks=immutable_chunks,
    )


def _chunk_page(
    page: StructuredPage,
    *,
    artifact_id: str,
    first_chunk_index: int,
    configuration: CorpusConfig,
) -> tuple[ChunkRecord, ...]:
    chunks: list[ChunkRecord] = []
    text = ""
    fragments: list[ChunkFragment] = []

    def flush() -> None:
        nonlocal text, fragments
        if not fragments:
            return
        chunk_index = first_chunk_index + len(chunks)
        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id_for(artifact_id, chunk_index),
                chunk_index=chunk_index,
                page_chunk_index=len(chunks) + 1,
                page_id=page.page_id,
                page_number=page.page_number,
                dimension_unit=page.dimension_unit,
                coordinate_origin=page.coordinate_origin,
                bounding_box=bounding_box_union([fragment.bounding_box for fragment in fragments]),
                text=text,
                character_count=len(text),
                content_fingerprint=text_fingerprint_for(text),
                fragments=tuple(fragments),
            )
        )
        text = ""
        fragments = []

    for span in page.spans:
        source_start = 0
        while source_start < len(span.text):
            if fragments and len(fragments) >= configuration.limits.max_fragments_per_chunk:
                flush()
            prefix = _separator(fragments[-1], span.source, configuration) if fragments else ""
            available = configuration.max_characters_per_chunk - len(text) - len(prefix)
            if available <= 0:
                flush()
                continue
            take = min(available, len(span.text) - source_start)
            chunk_start = len(text) + len(prefix)
            source_end = source_start + take
            text += prefix + span.text[source_start:source_end]
            fragments.append(
                ChunkFragment(
                    fragment_index=len(fragments) + 1,
                    span_id=span.span_id,
                    span_index=span.span_index,
                    source=span.source,
                    source_start=source_start,
                    source_end=source_end,
                    chunk_start=chunk_start,
                    chunk_end=chunk_start + take,
                    bounding_box=span.bounding_box,
                )
            )
            source_start = source_end
            if len(text) == configuration.max_characters_per_chunk:
                flush()
    flush()
    if len(chunks) > configuration.limits.max_chunks_per_page:
        raise CorpusLimitError(f"page {page.page_number} exceeds the corpus chunk limit")
    return tuple(chunks)


def _separator(
    previous: ChunkFragment,
    current_source: TextSpanSource,
    configuration: CorpusConfig,
) -> str:
    if (
        previous.source is TextSpanSource.EMBEDDED_WORD
        and current_source is TextSpanSource.EMBEDDED_WORD
    ):
        return configuration.embedded_word_separator
    return configuration.line_separator
