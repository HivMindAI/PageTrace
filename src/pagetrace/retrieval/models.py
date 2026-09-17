"""Immutable models for deterministic lexical retrieval and evaluation."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass

from pagetrace.corpus import is_chunk_id, is_corpus_artifact_id
from pagetrace.documents import DimensionUnit
from pagetrace.documents.models import document_id_for, is_sha256, page_id_for
from pagetrace.structure import BoundingBox, CoordinateOrigin

RETRIEVAL_SCHEMA_VERSION = 1
RETRIEVAL_PROCESSOR_NAME = "pagetrace-bm25"
RETRIEVAL_PROCESSOR_VERSION = "1"
TOKENIZER_NAME = "unicode-nfkc-casefold-word"
TOKENIZER_VERSION = "1"
_RESULT_ID_PATTERN = re.compile(r"^retrieval-sha256-[0-9a-f]{64}$")
_DATASET_ID_PATTERN = re.compile(r"^retrieval-dataset-sha256-[0-9a-f]{64}$")
_EVALUATION_ID_PATTERN = re.compile(r"^retrieval-evaluation-sha256-[0-9a-f]{64}$")
_QUERY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TOKEN_PATTERN = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*", re.UNICODE)


@dataclass(frozen=True, slots=True)
class RetrievalLimits:
    """Bounds for query text and tokenizer output."""

    max_query_characters: int = 10_000
    max_query_tokens: int = 1_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_query_characters", self.max_query_characters),
            ("max_query_tokens", self.max_query_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_RETRIEVAL_LIMITS = RetrievalLimits()


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    """Output-affecting BM25 parameters, cutoff, and query limits."""

    k1: float = 1.2
    b: float = 0.75
    top_k: int = 10
    limits: RetrievalLimits = DEFAULT_RETRIEVAL_LIMITS

    def __post_init__(self) -> None:
        if (
            isinstance(self.k1, bool)
            or not isinstance(self.k1, (int, float))
            or not math.isfinite(self.k1)
            or self.k1 <= 0
        ):
            raise ValueError("k1 must be a positive finite number")
        if (
            isinstance(self.b, bool)
            or not isinstance(self.b, (int, float))
            or not math.isfinite(self.b)
            or not 0 <= self.b <= 1
        ):
            raise ValueError("b must be a finite number from 0 to 1")
        if (
            isinstance(self.top_k, bool)
            or not isinstance(self.top_k, int)
            or not 1 <= self.top_k <= 1_000
        ):
            raise ValueError("top_k must be an integer from 1 to 1000")
        if not isinstance(self.limits, RetrievalLimits):
            raise ValueError("limits must be a RetrievalLimits value")


DEFAULT_RETRIEVAL_CONFIG = RetrievalConfig()


@dataclass(frozen=True, slots=True)
class RetrievalProcessorDescriptor:
    """Versioned BM25 and Unicode-tokenizer identity."""

    name: str = RETRIEVAL_PROCESSOR_NAME
    version: str = RETRIEVAL_PROCESSOR_VERSION
    tokenizer_name: str = TOKENIZER_NAME
    tokenizer_version: str = TOKENIZER_VERSION
    unicode_version: str = unicodedata.unidata_version

    def __post_init__(self) -> None:
        if self.name != RETRIEVAL_PROCESSOR_NAME:
            raise ValueError(f"retrieval processor name must be {RETRIEVAL_PROCESSOR_NAME}")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("retrieval processor version must not be empty")
        if self.tokenizer_name != TOKENIZER_NAME:
            raise ValueError(f"tokenizer name must be {TOKENIZER_NAME}")
        if not isinstance(self.tokenizer_version, str) or not self.tokenizer_version:
            raise ValueError("tokenizer version must not be empty")
        if not isinstance(self.unicode_version, str) or not self.unicode_version:
            raise ValueError("Unicode version must not be empty")


DEFAULT_RETRIEVAL_PROCESSOR = RetrievalProcessorDescriptor()


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """One ranked corpus chunk with exact page-region provenance."""

    rank: int
    score: float
    chunk_id: str
    chunk_index: int
    chunk_content_fingerprint: str
    page_id: str
    page_number: int
    dimension_unit: DimensionUnit
    coordinate_origin: CoordinateOrigin
    bounding_box: BoundingBox
    text: str
    matched_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("rank", self.rank),
            ("chunk_index", self.chunk_index),
            ("page_number", self.page_number),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive 1-based integer")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(self.score)
            or self.score <= 0
        ):
            raise ValueError("score must be a positive finite number")
        if not is_chunk_id(self.chunk_id):
            raise ValueError("chunk_id is not canonical")
        if not is_sha256(self.chunk_content_fingerprint):
            raise ValueError("chunk_content_fingerprint must be a SHA-256 digest")
        if not isinstance(self.dimension_unit, DimensionUnit):
            raise ValueError("dimension_unit must be points or pixels")
        if self.coordinate_origin is not CoordinateOrigin.TOP_LEFT:
            raise ValueError("coordinate_origin must be top_left")
        if not isinstance(self.bounding_box, BoundingBox):
            raise ValueError("bounding_box must be a BoundingBox")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("hit text must not be empty")
        if self.chunk_content_fingerprint != text_fingerprint_for(self.text):
            raise ValueError("chunk_content_fingerprint must match hit text")
        if not isinstance(self.matched_terms, tuple) or not self.matched_terms:
            raise ValueError("matched_terms must be a non-empty immutable tuple")
        if self.matched_terms != tuple(sorted(set(self.matched_terms))):
            raise ValueError("matched_terms must be unique and sorted")
        if any(not isinstance(term, str) or not term for term in self.matched_terms):
            raise ValueError("matched terms must be non-empty strings")


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Canonical BM25 result linked to one exact corpus artifact."""

    schema_version: int
    result_id: str
    document_id: str
    document_fingerprint: str
    source_corpus_artifact_id: str
    source_corpus_content_fingerprint: str
    processor: RetrievalProcessorDescriptor
    configuration: RetrievalConfig
    query: str
    query_fingerprint: str
    query_tokens: tuple[str, ...]
    corpus_chunk_count: int
    returned_hit_count: int
    content_fingerprint: str
    hits: tuple[RetrievalHit, ...]

    def __post_init__(self) -> None:
        if self.schema_version != RETRIEVAL_SCHEMA_VERSION:
            raise ValueError(f"unsupported retrieval schema version: {self.schema_version}")
        if not is_retrieval_result_id(self.result_id):
            raise ValueError("result_id is not a canonical retrieval identifier")
        if not is_sha256(self.document_fingerprint):
            raise ValueError("document_fingerprint must be a SHA-256 digest")
        if self.document_id != document_id_for(self.document_fingerprint):
            raise ValueError("document_id does not match document_fingerprint")
        if not is_corpus_artifact_id(self.source_corpus_artifact_id):
            raise ValueError("source_corpus_artifact_id is not canonical")
        if not is_sha256(self.source_corpus_content_fingerprint):
            raise ValueError("source_corpus_content_fingerprint must be a SHA-256 digest")
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must contain non-whitespace text")
        if self.query_fingerprint != text_fingerprint_for(self.query):
            raise ValueError("query_fingerprint must match query")
        if not isinstance(self.query_tokens, tuple) or not self.query_tokens:
            raise ValueError("query_tokens must be a non-empty immutable tuple")
        if any(not isinstance(token, str) or not token for token in self.query_tokens):
            raise ValueError("query tokens must be non-empty strings")
        if self.query_tokens != tokenize_text(self.query):
            raise ValueError("query_tokens must match the versioned tokenizer")
        if self.result_id != retrieval_result_id_for(
            self.document_fingerprint,
            self.source_corpus_artifact_id,
            self.source_corpus_content_fingerprint,
            self.processor,
            self.configuration,
            self.query,
        ):
            raise ValueError("result_id does not match retrieval inputs")
        for name, value in (
            ("corpus_chunk_count", self.corpus_chunk_count),
            ("returned_hit_count", self.returned_hit_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.hits, tuple):
            raise ValueError("hits must be an immutable tuple")
        if self.returned_hit_count != len(self.hits):
            raise ValueError("returned_hit_count must match hits")
        if len(self.hits) > min(self.configuration.top_k, self.corpus_chunk_count):
            raise ValueError("retrieval returned more hits than its cutoff or corpus")
        if self.content_fingerprint != retrieval_content_fingerprint_for(self.hits):
            raise ValueError("content_fingerprint must match retrieval hits")
        seen: set[str] = set()
        previous: RetrievalHit | None = None
        for expected_rank, hit in enumerate(self.hits, start=1):
            if hit.rank != expected_rank:
                raise ValueError("hits must use contiguous 1-based ranks")
            if hit.chunk_id in seen:
                raise ValueError("retrieval hits must have unique chunks")
            seen.add(hit.chunk_id)
            if hit.chunk_index > self.corpus_chunk_count:
                raise ValueError("hit chunk_index exceeds corpus_chunk_count")
            if hit.page_id != page_id_for(self.document_id, hit.page_number):
                raise ValueError("hit page_id does not match document and page number")
            if not set(hit.matched_terms).issubset(self.query_tokens):
                raise ValueError("hit matched_terms must come from query_tokens")
            if previous is not None and (
                hit.score > previous.score
                or (hit.score == previous.score and hit.chunk_index < previous.chunk_index)
            ):
                raise ValueError("hits must be ordered by descending score then chunk order")
            previous = hit


@dataclass(frozen=True, slots=True)
class RetrievalJudgment:
    """One query and its binary relevant chunk identities."""

    query_id: str
    query: str
    relevant_chunk_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or _QUERY_ID_PATTERN.fullmatch(self.query_id) is None:
            raise ValueError("query_id must be a safe 1-128 character identifier")
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must contain non-whitespace text")
        if not isinstance(self.relevant_chunk_ids, tuple) or not self.relevant_chunk_ids:
            raise ValueError("relevant_chunk_ids must be a non-empty immutable tuple")
        if any(not is_chunk_id(chunk_id) for chunk_id in self.relevant_chunk_ids):
            raise ValueError("relevant_chunk_ids must be canonical chunk identifiers")
        if len(set(self.relevant_chunk_ids)) != len(self.relevant_chunk_ids):
            raise ValueError("relevant_chunk_ids must be unique")


@dataclass(frozen=True, slots=True)
class RetrievalDataset:
    """Versioned binary relevance judgments for one exact corpus."""

    schema_version: int
    dataset_id: str
    source_corpus_artifact_id: str
    cases: tuple[RetrievalJudgment, ...]

    def __post_init__(self) -> None:
        if self.schema_version != RETRIEVAL_SCHEMA_VERSION:
            raise ValueError(f"unsupported retrieval schema version: {self.schema_version}")
        if not is_retrieval_dataset_id(self.dataset_id):
            raise ValueError("dataset_id is not a canonical retrieval dataset identifier")
        if not is_corpus_artifact_id(self.source_corpus_artifact_id):
            raise ValueError("source_corpus_artifact_id is not canonical")
        if not isinstance(self.cases, tuple) or not self.cases:
            raise ValueError("cases must be a non-empty immutable tuple")
        if len({case.query_id for case in self.cases}) != len(self.cases):
            raise ValueError("dataset query IDs must be unique")
        if self.dataset_id != retrieval_dataset_id_for(self.source_corpus_artifact_id, self.cases):
            raise ValueError("dataset_id does not match retrieval judgments")


@dataclass(frozen=True, slots=True)
class RetrievalCaseMetrics:
    """Binary relevance metrics for one evaluation query at a fixed cutoff."""

    query_id: str
    relevant_count: int
    retrieved_count: int
    relevant_retrieved_count: int
    reciprocal_rank: float
    precision: float
    recall: float
    average_precision: float
    ndcg: float

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or _QUERY_ID_PATTERN.fullmatch(self.query_id) is None:
            raise ValueError("query_id is invalid")
        for name, value in (
            ("relevant_count", self.relevant_count),
            ("retrieved_count", self.retrieved_count),
            ("relevant_retrieved_count", self.relevant_retrieved_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.relevant_count < 1 or self.relevant_retrieved_count > min(
            self.relevant_count, self.retrieved_count
        ):
            raise ValueError("retrieval metric counts are inconsistent")
        for metric_name, metric_value in (
            ("reciprocal_rank", self.reciprocal_rank),
            ("precision", self.precision),
            ("recall", self.recall),
            ("average_precision", self.average_precision),
            ("ndcg", self.ndcg),
        ):
            if (
                isinstance(metric_value, bool)
                or not isinstance(metric_value, (int, float))
                or not math.isfinite(metric_value)
                or not 0 <= metric_value <= 1
            ):
                raise ValueError(f"{metric_name} must be a finite number from 0 to 1")


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    """Aggregate deterministic retrieval evaluation for one corpus and dataset."""

    schema_version: int
    evaluation_id: str
    dataset_id: str
    source_corpus_artifact_id: str
    source_corpus_content_fingerprint: str
    processor: RetrievalProcessorDescriptor
    configuration: RetrievalConfig
    case_count: int
    mean_reciprocal_rank: float
    mean_precision: float
    mean_recall: float
    mean_average_precision: float
    mean_ndcg: float
    content_fingerprint: str
    cases: tuple[RetrievalCaseMetrics, ...]

    def __post_init__(self) -> None:
        if self.schema_version != RETRIEVAL_SCHEMA_VERSION:
            raise ValueError(f"unsupported retrieval schema version: {self.schema_version}")
        if not is_retrieval_evaluation_id(self.evaluation_id):
            raise ValueError("evaluation_id is not a canonical retrieval evaluation identifier")
        if not is_retrieval_dataset_id(self.dataset_id):
            raise ValueError("dataset_id is not canonical")
        if not is_corpus_artifact_id(self.source_corpus_artifact_id):
            raise ValueError("source_corpus_artifact_id is not canonical")
        if not is_sha256(self.source_corpus_content_fingerprint):
            raise ValueError("source_corpus_content_fingerprint must be a SHA-256 digest")
        if self.evaluation_id != retrieval_evaluation_id_for(
            self.dataset_id,
            self.source_corpus_artifact_id,
            self.source_corpus_content_fingerprint,
            self.processor,
            self.configuration,
        ):
            raise ValueError("evaluation_id does not match evaluation inputs")
        if not isinstance(self.cases, tuple) or not self.cases:
            raise ValueError("cases must be a non-empty immutable tuple")
        if self.case_count != len(self.cases):
            raise ValueError("case_count must match cases")
        if len({case.query_id for case in self.cases}) != len(self.cases):
            raise ValueError("evaluation query IDs must be unique")
        if self.content_fingerprint != evaluation_content_fingerprint_for(self.cases):
            raise ValueError("content_fingerprint must match evaluation cases")
        for name, value in (
            ("mean_reciprocal_rank", self.mean_reciprocal_rank),
            ("mean_precision", self.mean_precision),
            ("mean_recall", self.mean_recall),
            ("mean_average_precision", self.mean_average_precision),
            ("mean_ndcg", self.mean_ndcg),
        ):
            expected = rounded_mean(
                tuple(getattr(case, name.removeprefix("mean_")) for case in self.cases)
            )
            if value != expected:
                raise ValueError(f"{name} must match case metrics")


def create_retrieval_dataset(
    source_corpus_artifact_id: str, cases: tuple[RetrievalJudgment, ...]
) -> RetrievalDataset:
    return RetrievalDataset(
        schema_version=RETRIEVAL_SCHEMA_VERSION,
        dataset_id=retrieval_dataset_id_for(source_corpus_artifact_id, cases),
        source_corpus_artifact_id=source_corpus_artifact_id,
        cases=cases,
    )


def is_retrieval_result_id(value: str) -> bool:
    return isinstance(value, str) and _RESULT_ID_PATTERN.fullmatch(value) is not None


def is_retrieval_dataset_id(value: str) -> bool:
    return isinstance(value, str) and _DATASET_ID_PATTERN.fullmatch(value) is not None


def is_retrieval_evaluation_id(value: str) -> bool:
    return isinstance(value, str) and _EVALUATION_ID_PATTERN.fullmatch(value) is not None


def text_fingerprint_for(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def tokenize_text(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(match.group(0) for match in _TOKEN_PATTERN.finditer(normalized))


def retrieval_result_id_for(
    document_fingerprint: str,
    source_corpus_artifact_id: str,
    source_corpus_content_fingerprint: str,
    processor: RetrievalProcessorDescriptor,
    configuration: RetrievalConfig,
    query: str,
) -> str:
    if not is_sha256(document_fingerprint):
        raise ValueError("document_fingerprint must be a SHA-256 digest")
    if not is_corpus_artifact_id(source_corpus_artifact_id):
        raise ValueError("source_corpus_artifact_id must be canonical")
    if not is_sha256(source_corpus_content_fingerprint):
        raise ValueError("source_corpus_content_fingerprint must be a SHA-256 digest")
    payload = {
        "configuration": configuration_payload(configuration),
        "document_fingerprint": document_fingerprint,
        "processor": processor_payload(processor),
        "query": query,
        "schema_version": RETRIEVAL_SCHEMA_VERSION,
        "source_corpus_artifact_id": source_corpus_artifact_id,
        "source_corpus_content_fingerprint": source_corpus_content_fingerprint,
        "type": "pagetrace_retrieval",
    }
    return f"retrieval-sha256-{hashlib.sha256(canonical_json(payload)).hexdigest()}"


def retrieval_dataset_id_for(
    source_corpus_artifact_id: str, cases: tuple[RetrievalJudgment, ...]
) -> str:
    if not is_corpus_artifact_id(source_corpus_artifact_id):
        raise ValueError("source_corpus_artifact_id must be canonical")
    payload = {
        "cases": [judgment_payload(case) for case in cases],
        "schema_version": RETRIEVAL_SCHEMA_VERSION,
        "source_corpus_artifact_id": source_corpus_artifact_id,
        "type": "pagetrace_retrieval_dataset",
    }
    return f"retrieval-dataset-sha256-{hashlib.sha256(canonical_json(payload)).hexdigest()}"


def retrieval_evaluation_id_for(
    dataset_id: str,
    source_corpus_artifact_id: str,
    source_corpus_content_fingerprint: str,
    processor: RetrievalProcessorDescriptor,
    configuration: RetrievalConfig,
) -> str:
    if not is_retrieval_dataset_id(dataset_id):
        raise ValueError("dataset_id must be canonical")
    if not is_corpus_artifact_id(source_corpus_artifact_id):
        raise ValueError("source_corpus_artifact_id must be canonical")
    if not is_sha256(source_corpus_content_fingerprint):
        raise ValueError("source_corpus_content_fingerprint must be a SHA-256 digest")
    payload = {
        "configuration": configuration_payload(configuration),
        "dataset_id": dataset_id,
        "processor": processor_payload(processor),
        "schema_version": RETRIEVAL_SCHEMA_VERSION,
        "source_corpus_artifact_id": source_corpus_artifact_id,
        "source_corpus_content_fingerprint": source_corpus_content_fingerprint,
        "type": "pagetrace_retrieval_evaluation",
    }
    return f"retrieval-evaluation-sha256-{hashlib.sha256(canonical_json(payload)).hexdigest()}"


def retrieval_content_fingerprint_for(hits: tuple[RetrievalHit, ...]) -> str:
    return hashlib.sha256(canonical_json([hit_payload(hit) for hit in hits])).hexdigest()


def evaluation_content_fingerprint_for(cases: tuple[RetrievalCaseMetrics, ...]) -> str:
    return hashlib.sha256(
        canonical_json([case_metrics_payload(case) for case in cases])
    ).hexdigest()


def processor_payload(processor: RetrievalProcessorDescriptor) -> dict[str, object]:
    return {
        "name": processor.name,
        "tokenizer_name": processor.tokenizer_name,
        "tokenizer_version": processor.tokenizer_version,
        "unicode_version": processor.unicode_version,
        "version": processor.version,
    }


def configuration_payload(configuration: RetrievalConfig) -> dict[str, object]:
    return {
        "b": float(configuration.b),
        "k1": float(configuration.k1),
        "limits": {
            "max_query_characters": configuration.limits.max_query_characters,
            "max_query_tokens": configuration.limits.max_query_tokens,
        },
        "top_k": configuration.top_k,
    }


def hit_payload(hit: RetrievalHit) -> dict[str, object]:
    return {
        "bounding_box": box_payload(hit.bounding_box),
        "chunk_content_fingerprint": hit.chunk_content_fingerprint,
        "chunk_id": hit.chunk_id,
        "chunk_index": hit.chunk_index,
        "coordinate_origin": hit.coordinate_origin.value,
        "dimension_unit": hit.dimension_unit.value,
        "matched_terms": list(hit.matched_terms),
        "page_id": hit.page_id,
        "page_number": hit.page_number,
        "rank": hit.rank,
        "score": float(hit.score),
        "text": hit.text,
    }


def judgment_payload(judgment: RetrievalJudgment) -> dict[str, object]:
    return {
        "query": judgment.query,
        "query_id": judgment.query_id,
        "relevant_chunk_ids": list(judgment.relevant_chunk_ids),
    }


def case_metrics_payload(case: RetrievalCaseMetrics) -> dict[str, object]:
    return {
        "average_precision": float(case.average_precision),
        "ndcg": float(case.ndcg),
        "precision": float(case.precision),
        "query_id": case.query_id,
        "recall": float(case.recall),
        "reciprocal_rank": float(case.reciprocal_rank),
        "relevant_count": case.relevant_count,
        "relevant_retrieved_count": case.relevant_retrieved_count,
        "retrieved_count": case.retrieved_count,
    }


def box_payload(box: BoundingBox) -> dict[str, float]:
    return {
        "bottom": float(box.bottom),
        "top": float(box.top),
        "x0": float(box.x0),
        "x1": float(box.x1),
    }


def rounded_mean(values: tuple[float, ...]) -> float:
    return round(sum(values) / len(values), 12)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
