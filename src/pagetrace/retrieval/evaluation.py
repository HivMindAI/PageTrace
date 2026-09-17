"""Binary relevance evaluation for deterministic retrieval results."""

from __future__ import annotations

import math

from pagetrace.corpus import CorpusArtifact
from pagetrace.retrieval.errors import RetrievalEvaluationError
from pagetrace.retrieval.lexical import rank_corpus
from pagetrace.retrieval.models import (
    DEFAULT_RETRIEVAL_CONFIG,
    DEFAULT_RETRIEVAL_PROCESSOR,
    RETRIEVAL_SCHEMA_VERSION,
    RetrievalCaseMetrics,
    RetrievalConfig,
    RetrievalDataset,
    RetrievalEvaluation,
    RetrievalProcessorDescriptor,
    evaluation_content_fingerprint_for,
    retrieval_evaluation_id_for,
    rounded_mean,
)


def evaluate_retrieval(
    corpus: CorpusArtifact,
    dataset: RetrievalDataset,
    *,
    configuration: RetrievalConfig = DEFAULT_RETRIEVAL_CONFIG,
    processor: RetrievalProcessorDescriptor = DEFAULT_RETRIEVAL_PROCESSOR,
) -> RetrievalEvaluation:
    """Evaluate BM25 using binary judgments and a fixed top-k cutoff."""

    if not isinstance(corpus, CorpusArtifact):
        raise ValueError("corpus must be a CorpusArtifact")
    if not isinstance(dataset, RetrievalDataset):
        raise ValueError("dataset must be a RetrievalDataset")
    if dataset.source_corpus_artifact_id != corpus.artifact_id:
        raise RetrievalEvaluationError("dataset does not target the selected corpus")
    corpus_chunk_ids = {chunk.chunk_id for chunk in corpus.chunks}
    for case in dataset.cases:
        missing = set(case.relevant_chunk_ids) - corpus_chunk_ids
        if missing:
            raise RetrievalEvaluationError(
                f"query {case.query_id} references chunks outside the selected corpus"
            )

    case_metrics: list[RetrievalCaseMetrics] = []
    for case in dataset.cases:
        result = rank_corpus(
            corpus,
            case.query,
            configuration=configuration,
            processor=processor,
        )
        relevant = set(case.relevant_chunk_ids)
        ranked_ids = tuple(hit.chunk_id for hit in result.hits)
        relevant_ranks = tuple(
            rank for rank, chunk_id in enumerate(ranked_ids, start=1) if chunk_id in relevant
        )
        relevant_retrieved = len(relevant_ranks)
        precision = relevant_retrieved / configuration.top_k
        recall = relevant_retrieved / len(relevant)
        reciprocal_rank = 1 / relevant_ranks[0] if relevant_ranks else 0.0
        average_precision = _average_precision(relevant_ranks, len(relevant), configuration.top_k)
        ndcg = _ndcg(relevant_ranks, len(relevant), configuration.top_k)
        case_metrics.append(
            RetrievalCaseMetrics(
                query_id=case.query_id,
                relevant_count=len(relevant),
                retrieved_count=len(ranked_ids),
                relevant_retrieved_count=relevant_retrieved,
                reciprocal_rank=round(reciprocal_rank, 12),
                precision=round(precision, 12),
                recall=round(recall, 12),
                average_precision=round(average_precision, 12),
                ndcg=round(ndcg, 12),
            )
        )

    cases = tuple(case_metrics)
    return RetrievalEvaluation(
        schema_version=RETRIEVAL_SCHEMA_VERSION,
        evaluation_id=retrieval_evaluation_id_for(
            dataset.dataset_id,
            corpus.artifact_id,
            corpus.content_fingerprint,
            processor,
            configuration,
        ),
        dataset_id=dataset.dataset_id,
        source_corpus_artifact_id=corpus.artifact_id,
        source_corpus_content_fingerprint=corpus.content_fingerprint,
        processor=processor,
        configuration=configuration,
        case_count=len(cases),
        mean_reciprocal_rank=rounded_mean(tuple(case.reciprocal_rank for case in cases)),
        mean_precision=rounded_mean(tuple(case.precision for case in cases)),
        mean_recall=rounded_mean(tuple(case.recall for case in cases)),
        mean_average_precision=rounded_mean(tuple(case.average_precision for case in cases)),
        mean_ndcg=rounded_mean(tuple(case.ndcg for case in cases)),
        content_fingerprint=evaluation_content_fingerprint_for(cases),
        cases=cases,
    )


def _average_precision(relevant_ranks: tuple[int, ...], relevant_count: int, cutoff: int) -> float:
    if not relevant_ranks:
        return 0.0
    precision_sum = sum(index / rank for index, rank in enumerate(relevant_ranks, start=1))
    return precision_sum / min(relevant_count, cutoff)


def _ndcg(relevant_ranks: tuple[int, ...], relevant_count: int, cutoff: int) -> float:
    ideal_count = min(relevant_count, cutoff)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    actual = sum(1 / math.log2(rank + 1) for rank in relevant_ranks)
    return actual / ideal
