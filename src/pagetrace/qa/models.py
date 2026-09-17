"""Immutable models for deterministic evidence-grounded answers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum

from pagetrace.documents.models import is_sha256
from pagetrace.retrieval import RetrievalResult, is_retrieval_result_id, tokenize

QA_SCHEMA_VERSION = 1
QA_PROCESSOR_NAME = "pagetrace-extractive-qa"
QA_PROCESSOR_VERSION = "1"
SENTENCE_SEGMENTER_NAME = "unicode-line-terminal"
SENTENCE_SEGMENTER_VERSION = "1"
_ANSWER_ID_PATTERN = re.compile(r"^answer-sha256-[0-9a-f]{64}$")


class QaStatus(StrEnum):
    """Whether evidence supported an answer."""

    ANSWERED = "answered"
    ABSTAINED = "abstained"


class AbstentionReason(StrEnum):
    """Explicit reason that PageTrace declined to answer."""

    NO_RETRIEVAL_HITS = "no_retrieval_hits"
    INSUFFICIENT_QUERY_TERM_COVERAGE = "insufficient_query_term_coverage"
    ANSWER_CHARACTER_LIMIT = "answer_character_limit"


@dataclass(frozen=True, slots=True)
class QaConfig:
    """Output-affecting evidence selection and answer bounds."""

    max_evidence_items: int = 3
    max_answer_characters: int = 4_000
    minimum_query_term_coverage: float = 0.25
    evidence_separator: str = "\n"

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_evidence_items, bool)
            or not isinstance(self.max_evidence_items, int)
            or not 1 <= self.max_evidence_items <= 100
        ):
            raise ValueError("max_evidence_items must be an integer from 1 to 100")
        if (
            isinstance(self.max_answer_characters, bool)
            or not isinstance(self.max_answer_characters, int)
            or not 1 <= self.max_answer_characters <= 100_000
        ):
            raise ValueError("max_answer_characters must be an integer from 1 to 100000")
        if (
            isinstance(self.minimum_query_term_coverage, bool)
            or not isinstance(self.minimum_query_term_coverage, (int, float))
            or not math.isfinite(self.minimum_query_term_coverage)
            or not 0 < self.minimum_query_term_coverage <= 1
        ):
            raise ValueError("minimum_query_term_coverage must be greater than 0 and at most 1")
        if not isinstance(self.evidence_separator, str) or not self.evidence_separator:
            raise ValueError("evidence_separator must not be empty")
        if len(self.evidence_separator) > 10:
            raise ValueError("evidence_separator must contain at most 10 characters")


DEFAULT_QA_CONFIG = QaConfig()


@dataclass(frozen=True, slots=True)
class QaProcessorDescriptor:
    """Versioned extractive answer and sentence-boundary identity."""

    name: str = QA_PROCESSOR_NAME
    version: str = QA_PROCESSOR_VERSION
    sentence_segmenter_name: str = SENTENCE_SEGMENTER_NAME
    sentence_segmenter_version: str = SENTENCE_SEGMENTER_VERSION

    def __post_init__(self) -> None:
        if self.name != QA_PROCESSOR_NAME:
            raise ValueError(f"QA processor name must be {QA_PROCESSOR_NAME}")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("QA processor version must not be empty")
        if self.sentence_segmenter_name != SENTENCE_SEGMENTER_NAME:
            raise ValueError(f"sentence segmenter must be {SENTENCE_SEGMENTER_NAME}")
        if (
            not isinstance(self.sentence_segmenter_version, str)
            or not self.sentence_segmenter_version
        ):
            raise ValueError("sentence segmenter version must not be empty")


DEFAULT_QA_PROCESSOR = QaProcessorDescriptor()


@dataclass(frozen=True, slots=True)
class EvidenceCitation:
    """An exact character slice of one retrieved corpus chunk."""

    citation_index: int
    retrieval_rank: int
    chunk_id: str
    excerpt_start: int
    excerpt_end: int
    excerpt: str
    excerpt_fingerprint: str
    matched_terms: tuple[str, ...]
    query_term_coverage: float

    def __post_init__(self) -> None:
        for name, value in (
            ("citation_index", self.citation_index),
            ("retrieval_rank", self.retrieval_rank),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive 1-based integer")
        for name, value in (
            ("excerpt_start", self.excerpt_start),
            ("excerpt_end", self.excerpt_end),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.excerpt_end <= self.excerpt_start:
            raise ValueError("excerpt_end must be greater than excerpt_start")
        if not isinstance(self.excerpt, str) or not self.excerpt:
            raise ValueError("excerpt must not be empty")
        if self.excerpt_end - self.excerpt_start != len(self.excerpt):
            raise ValueError("excerpt offsets must match excerpt length")
        if not is_sha256(self.excerpt_fingerprint):
            raise ValueError("excerpt_fingerprint must be a SHA-256 digest")
        if self.excerpt_fingerprint != text_fingerprint_for(self.excerpt):
            raise ValueError("excerpt_fingerprint must match excerpt")
        if not isinstance(self.matched_terms, tuple) or not self.matched_terms:
            raise ValueError("matched_terms must be a non-empty immutable tuple")
        if self.matched_terms != tuple(sorted(set(self.matched_terms))):
            raise ValueError("matched_terms must be unique and sorted")
        if any(not isinstance(term, str) or not term for term in self.matched_terms):
            raise ValueError("matched_terms must contain non-empty strings")
        if (
            isinstance(self.query_term_coverage, bool)
            or not isinstance(self.query_term_coverage, (int, float))
            or not math.isfinite(self.query_term_coverage)
            or not 0 < self.query_term_coverage <= 1
        ):
            raise ValueError("query_term_coverage must be greater than 0 and at most 1")


@dataclass(frozen=True, slots=True)
class QaResult:
    """An answer whose entire substantive text is cited retrieved evidence."""

    schema_version: int
    answer_id: str
    processor: QaProcessorDescriptor
    configuration: QaConfig
    status: QaStatus
    abstention_reason: AbstentionReason | None
    answer: str | None
    answer_fingerprint: str | None
    content_fingerprint: str
    retrieval: RetrievalResult
    citations: tuple[EvidenceCitation, ...]

    def __post_init__(self) -> None:
        if self.schema_version != QA_SCHEMA_VERSION:
            raise ValueError(f"unsupported QA schema version: {self.schema_version}")
        if not is_answer_id(self.answer_id):
            raise ValueError("answer_id is not canonical")
        if not isinstance(self.processor, QaProcessorDescriptor):
            raise ValueError("processor must be a QaProcessorDescriptor")
        if not isinstance(self.configuration, QaConfig):
            raise ValueError("configuration must be a QaConfig")
        if not isinstance(self.status, QaStatus):
            raise ValueError("status must be a QaStatus")
        if not isinstance(self.retrieval, RetrievalResult):
            raise ValueError("retrieval must be a RetrievalResult")
        if not isinstance(self.citations, tuple):
            raise ValueError("citations must be an immutable tuple")
        if self.answer_id != answer_id_for(self.retrieval, self.processor, self.configuration):
            raise ValueError("answer_id does not match answer inputs")
        if self.content_fingerprint != qa_content_fingerprint_for(
            self.status,
            self.abstention_reason,
            self.answer,
            self.citations,
        ):
            raise ValueError("content_fingerprint must match answer content")
        if self.status is QaStatus.ANSWERED:
            self._validate_answered()
        else:
            self._validate_abstained()

    def _validate_answered(self) -> None:
        if self.abstention_reason is not None:
            raise ValueError("answered results cannot have an abstention reason")
        if not isinstance(self.answer, str) or not self.answer:
            raise ValueError("answered results must contain answer text")
        if self.answer_fingerprint != text_fingerprint_for(self.answer):
            raise ValueError("answer_fingerprint must match answer")
        if not self.citations:
            raise ValueError("answered results must contain citations")
        if len(self.citations) > self.configuration.max_evidence_items:
            raise ValueError("citations exceed max_evidence_items")
        if len(self.answer) > self.configuration.max_answer_characters:
            raise ValueError("answer exceeds max_answer_characters")
        expected_answer = self.configuration.evidence_separator.join(
            citation.excerpt for citation in self.citations
        )
        if self.answer != expected_answer:
            raise ValueError("answer must contain only cited excerpts and configured separators")
        self._validate_citations()

    def _validate_abstained(self) -> None:
        if not isinstance(self.abstention_reason, AbstentionReason):
            raise ValueError("abstained results must have an abstention reason")
        if self.answer is not None or self.answer_fingerprint is not None:
            raise ValueError("abstained results cannot contain an answer")
        if self.citations:
            raise ValueError("abstained results cannot contain citations")
        no_hits = not self.retrieval.hits
        if no_hits != (self.abstention_reason is AbstentionReason.NO_RETRIEVAL_HITS):
            raise ValueError("abstention reason must agree with retrieval hit availability")

    def _validate_citations(self) -> None:
        query_terms = set(self.retrieval.query_tokens)
        seen: set[tuple[str, int, int]] = set()
        for expected_index, citation in enumerate(self.citations, start=1):
            if citation.citation_index != expected_index:
                raise ValueError("citations must use contiguous 1-based indexes")
            if citation.retrieval_rank > len(self.retrieval.hits):
                raise ValueError("citation retrieval rank is outside the source result")
            hit = self.retrieval.hits[citation.retrieval_rank - 1]
            if citation.chunk_id != hit.chunk_id:
                raise ValueError("citation chunk does not match its retrieval rank")
            if citation.excerpt_end > len(hit.text):
                raise ValueError("citation excerpt is outside the retrieved chunk")
            if hit.text[citation.excerpt_start : citation.excerpt_end] != citation.excerpt:
                raise ValueError("citation excerpt does not match retrieved evidence")
            matched = tuple(sorted(set(tokenize(citation.excerpt)) & query_terms))
            if citation.matched_terms != matched:
                raise ValueError("citation matched_terms do not match its exact evidence")
            coverage = round(len(matched) / len(query_terms), 12)
            if citation.query_term_coverage != coverage:
                raise ValueError("citation query_term_coverage does not match its evidence")
            if coverage < self.configuration.minimum_query_term_coverage:
                raise ValueError("citation is below minimum_query_term_coverage")
            identity = (citation.chunk_id, citation.excerpt_start, citation.excerpt_end)
            if identity in seen:
                raise ValueError("citations must not duplicate evidence slices")
            seen.add(identity)


def is_answer_id(value: str) -> bool:
    return isinstance(value, str) and _ANSWER_ID_PATTERN.fullmatch(value) is not None


def answer_id_for(
    retrieval: RetrievalResult,
    processor: QaProcessorDescriptor,
    configuration: QaConfig,
) -> str:
    if not isinstance(retrieval, RetrievalResult) or not is_retrieval_result_id(
        retrieval.result_id
    ):
        raise ValueError("retrieval must be a canonical RetrievalResult")
    payload = {
        "configuration": configuration_payload(configuration),
        "processor": processor_payload(processor),
        "retrieval_content_fingerprint": retrieval.content_fingerprint,
        "retrieval_result_id": retrieval.result_id,
        "schema_version": QA_SCHEMA_VERSION,
        "type": "pagetrace_evidence_grounded_answer",
    }
    return f"answer-sha256-{hashlib.sha256(canonical_json(payload)).hexdigest()}"


def qa_content_fingerprint_for(
    status: QaStatus,
    abstention_reason: AbstentionReason | None,
    answer: str | None,
    citations: tuple[EvidenceCitation, ...],
) -> str:
    payload = {
        "abstention_reason": abstention_reason.value if abstention_reason is not None else None,
        "answer": answer,
        "citations": [citation_payload(citation) for citation in citations],
        "status": status.value,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def processor_payload(processor: QaProcessorDescriptor) -> dict[str, object]:
    return {
        "name": processor.name,
        "sentence_segmenter_name": processor.sentence_segmenter_name,
        "sentence_segmenter_version": processor.sentence_segmenter_version,
        "version": processor.version,
    }


def configuration_payload(configuration: QaConfig) -> dict[str, object]:
    return {
        "evidence_separator": configuration.evidence_separator,
        "max_answer_characters": configuration.max_answer_characters,
        "max_evidence_items": configuration.max_evidence_items,
        "minimum_query_term_coverage": float(configuration.minimum_query_term_coverage),
    }


def citation_payload(citation: EvidenceCitation) -> dict[str, object]:
    return {
        "chunk_id": citation.chunk_id,
        "citation_index": citation.citation_index,
        "excerpt": citation.excerpt,
        "excerpt_end": citation.excerpt_end,
        "excerpt_fingerprint": citation.excerpt_fingerprint,
        "excerpt_start": citation.excerpt_start,
        "matched_terms": list(citation.matched_terms),
        "query_term_coverage": float(citation.query_term_coverage),
        "retrieval_rank": citation.retrieval_rank,
    }


def text_fingerprint_for(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
