"""Transparent deterministic Unicode tokenization and BM25 ranking."""

from __future__ import annotations

import math
from collections import Counter

from pagetrace.corpus import CorpusArtifact
from pagetrace.retrieval.errors import RetrievalLimitError, RetrievalQueryError
from pagetrace.retrieval.models import (
    DEFAULT_RETRIEVAL_CONFIG,
    DEFAULT_RETRIEVAL_PROCESSOR,
    RETRIEVAL_SCHEMA_VERSION,
    RetrievalConfig,
    RetrievalHit,
    RetrievalProcessorDescriptor,
    RetrievalResult,
    retrieval_content_fingerprint_for,
    retrieval_result_id_for,
    text_fingerprint_for,
    tokenize_text,
)


def tokenize(text: str) -> tuple[str, ...]:
    """Tokenize NFKC-normalized, case-folded text with a fixed Unicode word rule."""

    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return tokenize_text(text)


def rank_corpus(
    corpus: CorpusArtifact,
    query: str,
    *,
    configuration: RetrievalConfig = DEFAULT_RETRIEVAL_CONFIG,
    processor: RetrievalProcessorDescriptor = DEFAULT_RETRIEVAL_PROCESSOR,
) -> RetrievalResult:
    """Rank positive-scoring corpus chunks with deterministic BM25."""

    if not isinstance(corpus, CorpusArtifact):
        raise ValueError("corpus must be a CorpusArtifact")
    if not isinstance(configuration, RetrievalConfig):
        raise ValueError("configuration must be a RetrievalConfig")
    if not isinstance(processor, RetrievalProcessorDescriptor):
        raise ValueError("processor must be a RetrievalProcessorDescriptor")
    if not isinstance(query, str) or not query.strip():
        raise RetrievalQueryError("query must contain non-whitespace text")
    if len(query) > configuration.limits.max_query_characters:
        raise RetrievalLimitError("query exceeds the retrieval character limit")
    query_tokens = tokenize(query)
    if not query_tokens:
        raise RetrievalQueryError("query contains no lexical terms")
    if len(query_tokens) > configuration.limits.max_query_tokens:
        raise RetrievalLimitError("query exceeds the retrieval token limit")

    document_tokens = tuple(tokenize(chunk.text) for chunk in corpus.chunks)
    term_frequencies = tuple(Counter(tokens) for tokens in document_tokens)
    document_count = len(corpus.chunks)
    average_length = (
        sum(len(tokens) for tokens in document_tokens) / document_count if document_count else 0.0
    )
    query_terms = tuple(sorted(set(query_tokens)))
    document_frequencies = {
        term: sum(1 for frequencies in term_frequencies if frequencies.get(term, 0) > 0)
        for term in query_terms
    }

    scored: list[tuple[float, int, tuple[str, ...]]] = []
    for index, (tokens, frequencies) in enumerate(
        zip(document_tokens, term_frequencies, strict=True)
    ):
        matched = tuple(term for term in query_terms if frequencies.get(term, 0) > 0)
        if not matched or average_length == 0:
            continue
        score = sum(
            _bm25_term_score(
                term_frequency=frequencies[term],
                document_frequency=document_frequencies[term],
                document_length=len(tokens),
                document_count=document_count,
                average_length=average_length,
                configuration=configuration,
            )
            for term in matched
        )
        rounded_score = round(score, 12)
        if rounded_score > 0:
            scored.append((rounded_score, index, matched))
    scored.sort(key=lambda item: (-item[0], corpus.chunks[item[1]].chunk_index))

    hits = tuple(
        RetrievalHit(
            rank=rank,
            score=score,
            chunk_id=corpus.chunks[index].chunk_id,
            chunk_index=corpus.chunks[index].chunk_index,
            chunk_content_fingerprint=corpus.chunks[index].content_fingerprint,
            page_id=corpus.chunks[index].page_id,
            page_number=corpus.chunks[index].page_number,
            dimension_unit=corpus.chunks[index].dimension_unit,
            coordinate_origin=corpus.chunks[index].coordinate_origin,
            bounding_box=corpus.chunks[index].bounding_box,
            text=corpus.chunks[index].text,
            matched_terms=matched,
        )
        for rank, (score, index, matched) in enumerate(scored[: configuration.top_k], start=1)
    )
    return RetrievalResult(
        schema_version=RETRIEVAL_SCHEMA_VERSION,
        result_id=retrieval_result_id_for(
            corpus.document_fingerprint,
            corpus.artifact_id,
            corpus.content_fingerprint,
            processor,
            configuration,
            query,
        ),
        document_id=corpus.document_id,
        document_fingerprint=corpus.document_fingerprint,
        source_corpus_artifact_id=corpus.artifact_id,
        source_corpus_content_fingerprint=corpus.content_fingerprint,
        processor=processor,
        configuration=configuration,
        query=query,
        query_fingerprint=text_fingerprint_for(query),
        query_tokens=query_tokens,
        corpus_chunk_count=corpus.chunk_count,
        returned_hit_count=len(hits),
        content_fingerprint=retrieval_content_fingerprint_for(hits),
        hits=hits,
    )


def _bm25_term_score(
    *,
    term_frequency: int,
    document_frequency: int,
    document_length: int,
    document_count: int,
    average_length: float,
    configuration: RetrievalConfig,
) -> float:
    inverse_document_frequency = math.log(
        1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
    )
    normalization = configuration.k1 * (
        1 - configuration.b + configuration.b * document_length / average_length
    )
    return inverse_document_frequency * (
        term_frequency * (configuration.k1 + 1) / (term_frequency + normalization)
    )
