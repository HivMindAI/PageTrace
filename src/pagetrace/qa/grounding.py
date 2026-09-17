"""Deterministic extractive answering over verified retrieval results."""

from __future__ import annotations

from dataclasses import dataclass

from pagetrace.qa.models import (
    DEFAULT_QA_CONFIG,
    DEFAULT_QA_PROCESSOR,
    QA_SCHEMA_VERSION,
    AbstentionReason,
    EvidenceCitation,
    QaConfig,
    QaProcessorDescriptor,
    QaResult,
    QaStatus,
    answer_id_for,
    qa_content_fingerprint_for,
    text_fingerprint_for,
)
from pagetrace.retrieval import RetrievalResult, tokenize


@dataclass(frozen=True, slots=True)
class _Candidate:
    retrieval_rank: int
    chunk_id: str
    start: int
    end: int
    text: str
    matched_terms: tuple[str, ...]
    coverage: float


def answer_from_retrieval(
    retrieval: RetrievalResult,
    *,
    configuration: QaConfig = DEFAULT_QA_CONFIG,
    processor: QaProcessorDescriptor = DEFAULT_QA_PROCESSOR,
) -> QaResult:
    """Return exact evidence excerpts or an explicit abstention."""

    if not isinstance(retrieval, RetrievalResult):
        raise ValueError("retrieval must be a RetrievalResult")
    if not isinstance(configuration, QaConfig):
        raise ValueError("configuration must be a QaConfig")
    if not isinstance(processor, QaProcessorDescriptor):
        raise ValueError("processor must be a QaProcessorDescriptor")
    if not retrieval.hits:
        return _abstained(
            retrieval,
            AbstentionReason.NO_RETRIEVAL_HITS,
            configuration=configuration,
            processor=processor,
        )

    query_terms = set(retrieval.query_tokens)
    candidates: list[_Candidate] = []
    for hit in retrieval.hits:
        for start, end in sentence_spans(hit.text):
            excerpt = hit.text[start:end]
            matched = tuple(sorted(set(tokenize(excerpt)) & query_terms))
            coverage = round(len(matched) / len(query_terms), 12)
            if matched and coverage >= configuration.minimum_query_term_coverage:
                candidates.append(
                    _Candidate(
                        retrieval_rank=hit.rank,
                        chunk_id=hit.chunk_id,
                        start=start,
                        end=end,
                        text=excerpt,
                        matched_terms=matched,
                        coverage=coverage,
                    )
                )
    if not candidates:
        return _abstained(
            retrieval,
            AbstentionReason.INSUFFICIENT_QUERY_TERM_COVERAGE,
            configuration=configuration,
            processor=processor,
        )

    candidates.sort(key=lambda item: (-item.coverage, item.retrieval_rank, item.start, item.end))
    citations: list[EvidenceCitation] = []
    answer_characters = 0
    for candidate in candidates:
        if len(citations) >= configuration.max_evidence_items:
            break
        separator_length = len(configuration.evidence_separator) if citations else 0
        remaining = configuration.max_answer_characters - answer_characters - separator_length
        if remaining <= 0:
            break
        selected = candidate.text[:remaining].rstrip()
        if not selected:
            continue
        selected_end = candidate.start + len(selected)
        matched = tuple(sorted(set(tokenize(selected)) & query_terms))
        coverage = round(len(matched) / len(query_terms), 12)
        if not matched or coverage < configuration.minimum_query_term_coverage:
            continue
        citations.append(
            EvidenceCitation(
                citation_index=len(citations) + 1,
                retrieval_rank=candidate.retrieval_rank,
                chunk_id=candidate.chunk_id,
                excerpt_start=candidate.start,
                excerpt_end=selected_end,
                excerpt=selected,
                excerpt_fingerprint=text_fingerprint_for(selected),
                matched_terms=matched,
                query_term_coverage=coverage,
            )
        )
        answer_characters += separator_length + len(selected)

    if not citations:
        return _abstained(
            retrieval,
            AbstentionReason.ANSWER_CHARACTER_LIMIT,
            configuration=configuration,
            processor=processor,
        )
    citation_tuple = tuple(citations)
    answer = configuration.evidence_separator.join(citation.excerpt for citation in citation_tuple)
    status = QaStatus.ANSWERED
    return QaResult(
        schema_version=QA_SCHEMA_VERSION,
        answer_id=answer_id_for(retrieval, processor, configuration),
        processor=processor,
        configuration=configuration,
        status=status,
        abstention_reason=None,
        answer=answer,
        answer_fingerprint=text_fingerprint_for(answer),
        content_fingerprint=qa_content_fingerprint_for(status, None, answer, citation_tuple),
        retrieval=retrieval,
        citations=citation_tuple,
    )


def sentence_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Return trimmed exact spans split at lines and terminal punctuation."""

    if not isinstance(text, str):
        raise ValueError("text must be a string")
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(text):
        character = text[index]
        line_boundary = character in "\r\n"
        terminal_boundary = character in ".!?" and (
            index + 1 == len(text) or text[index + 1].isspace()
        )
        if line_boundary:
            _append_trimmed_span(text, start, index, spans)
            if character == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                index += 1
            start = index + 1
        elif terminal_boundary:
            _append_trimmed_span(text, start, index + 1, spans)
            start = index + 1
        index += 1
    _append_trimmed_span(text, start, len(text), spans)
    return tuple(spans)


def _append_trimmed_span(text: str, start: int, end: int, spans: list[tuple[int, int]]) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        spans.append((start, end))


def _abstained(
    retrieval: RetrievalResult,
    reason: AbstentionReason,
    *,
    configuration: QaConfig,
    processor: QaProcessorDescriptor,
) -> QaResult:
    status = QaStatus.ABSTAINED
    citations: tuple[EvidenceCitation, ...] = ()
    return QaResult(
        schema_version=QA_SCHEMA_VERSION,
        answer_id=answer_id_for(retrieval, processor, configuration),
        processor=processor,
        configuration=configuration,
        status=status,
        abstention_reason=reason,
        answer=None,
        answer_fingerprint=None,
        content_fingerprint=qa_content_fingerprint_for(status, reason, None, citations),
        retrieval=retrieval,
        citations=citations,
    )
