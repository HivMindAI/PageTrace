from __future__ import annotations

from dataclasses import replace

import pytest

import pagetrace.retrieval.processing as retrieval_processing
from pagetrace.corpus import CorpusArtifact, build_corpus_artifact
from pagetrace.retrieval import (
    RetrievalConfig,
    RetrievalEvaluationError,
    RetrievalJudgment,
    RetrievalLimitError,
    RetrievalLimits,
    RetrievalQueryError,
    create_retrieval_dataset,
    evaluate_retrieval,
    rank_corpus,
    retrieve,
    tokenize,
)
from tests.test_corpus_models import _source


def test_unicode_tokenizer_is_explicit_casefolded_and_normalized() -> None:
    assert tokenize("CAFÉ café \uff21\uff22\uff23 snake_case can't can\u2019t") == (
        "café",
        "café",
        "abc",
        "snake",
        "case",
        "can't",
        "can\u2019t",
    )
    with pytest.raises(ValueError, match="string"):
        tokenize(1)  # type: ignore[arg-type]


def test_bm25_ranking_is_deterministic_and_preserves_provenance() -> None:
    corpus = _corpus()

    result = rank_corpus(corpus, "BETA")
    replay = rank_corpus(corpus, "BETA")

    assert result == replay
    assert result.query_tokens == ("beta",)
    assert [hit.chunk_index for hit in result.hits] == [1, 2]
    assert [hit.rank for hit in result.hits] == [1, 2]
    assert all(hit.matched_terms == ("beta",) for hit in result.hits)
    assert result.hits[0].page_id == corpus.chunks[0].page_id
    assert result.hits[0].bounding_box == corpus.chunks[0].bounding_box
    assert result.hits[0].text == corpus.chunks[0].text
    assert result.hits[0].chunk_content_fingerprint == corpus.chunks[0].content_fingerprint


def test_term_frequency_and_top_k_control_ranking() -> None:
    corpus = build_corpus_artifact(_source((("term term term",), ("term other",), ("unrelated",))))
    result = rank_corpus(corpus, "term", configuration=RetrievalConfig(top_k=1))

    assert result.returned_hit_count == 1
    assert result.hits[0].chunk_index == 1


def test_no_match_returns_empty_result_and_empty_corpus_is_valid() -> None:
    result = rank_corpus(_corpus(), "missing")
    empty = rank_corpus(build_corpus_artifact(_source(((),))), "missing")

    assert result.hits == ()
    assert result.returned_hit_count == 0
    assert empty.corpus_chunk_count == 0
    assert empty.hits == ()


@pytest.mark.parametrize(
    ("query", "configuration", "error", "message"),
    [
        (" ", RetrievalConfig(), RetrievalQueryError, "non-whitespace"),
        ("!!!", RetrievalConfig(), RetrievalQueryError, "no lexical"),
        (
            "long",
            RetrievalConfig(limits=RetrievalLimits(max_query_characters=3)),
            RetrievalLimitError,
            "character limit",
        ),
        (
            "one two",
            RetrievalConfig(limits=RetrievalLimits(max_query_tokens=1)),
            RetrievalLimitError,
            "token limit",
        ),
    ],
)
def test_query_validation_is_bounded(
    query: str,
    configuration: RetrievalConfig,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        rank_corpus(_corpus(), query, configuration=configuration)


def test_binary_relevance_metrics_are_exact_at_cutoff() -> None:
    corpus = _corpus()
    dataset = create_retrieval_dataset(
        corpus.artifact_id,
        (
            RetrievalJudgment("q1", "alpha", (corpus.chunks[0].chunk_id,)),
            RetrievalJudgment("q2", "beta", (corpus.chunks[1].chunk_id,)),
            RetrievalJudgment("q3", "missing", (corpus.chunks[2].chunk_id,)),
        ),
    )

    evaluation = evaluate_retrieval(corpus, dataset, configuration=RetrievalConfig(top_k=2))

    assert evaluation.case_count == 3
    first, second, third = evaluation.cases
    assert (first.precision, first.recall, first.reciprocal_rank) == (0.5, 1.0, 1.0)
    assert second.precision == 0.5
    assert second.recall == 1.0
    assert second.reciprocal_rank == 0.5
    assert second.average_precision == 0.5
    assert second.ndcg == round(1 / 1.584962500721156, 12)
    assert (
        third.precision,
        third.recall,
        third.reciprocal_rank,
        third.average_precision,
        third.ndcg,
    ) == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert evaluation.mean_recall == round(2 / 3, 12)


def test_evaluation_rejects_wrong_corpus_and_unknown_chunks() -> None:
    corpus = _corpus()
    other = build_corpus_artifact(_source((("other",),)))
    dataset = create_retrieval_dataset(
        corpus.artifact_id,
        (RetrievalJudgment("q1", "alpha", (corpus.chunks[0].chunk_id,)),),
    )
    with pytest.raises(RetrievalEvaluationError, match="does not target"):
        evaluate_retrieval(other, dataset)

    unknown = replace(dataset.cases[0], relevant_chunk_ids=(other.chunks[0].chunk_id,))
    invalid_for_corpus = create_retrieval_dataset(corpus.artifact_id, (unknown,))
    with pytest.raises(RetrievalEvaluationError, match="outside"):
        evaluate_retrieval(corpus, invalid_for_corpus)


def test_public_retrieve_loads_verified_corpus(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _corpus()
    monkeypatch.setattr(
        retrieval_processing, "load_corpus_artifact", lambda *_args, **_kwargs: corpus
    )

    result = retrieve(
        corpus.document_id,
        corpus.artifact_id,
        "alpha",
        store=tmp_path,  # type: ignore[arg-type]
    )

    assert result.hits[0].chunk_id == corpus.chunks[0].chunk_id


def _corpus() -> CorpusArtifact:
    return build_corpus_artifact(_source((("alpha beta",), ("beta gamma",), ("delta",))))
