from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pagetrace.retrieval import (
    DEFAULT_RETRIEVAL_CONFIG,
    DEFAULT_RETRIEVAL_PROCESSOR,
    RetrievalConfig,
    RetrievalHit,
    RetrievalIntegrityError,
    RetrievalJudgment,
    RetrievalLimits,
    RetrievalProcessorDescriptor,
    RetrievalResult,
    create_retrieval_dataset,
    deserialize_retrieval_dataset,
    deserialize_retrieval_evaluation,
    deserialize_retrieval_result,
    evaluate_retrieval,
    is_retrieval_dataset_id,
    is_retrieval_evaluation_id,
    is_retrieval_result_id,
    rank_corpus,
    serialize_retrieval_dataset,
    serialize_retrieval_evaluation,
    serialize_retrieval_result,
)
from pagetrace.retrieval.models import retrieval_content_fingerprint_for
from tests.test_retrieval import _corpus


def test_default_retrieval_configuration_and_processor_are_explicit() -> None:
    assert DEFAULT_RETRIEVAL_CONFIG.k1 == 1.2
    assert DEFAULT_RETRIEVAL_CONFIG.b == 0.75
    assert DEFAULT_RETRIEVAL_CONFIG.top_k == 10
    assert DEFAULT_RETRIEVAL_CONFIG.limits.max_query_characters == 10_000
    assert DEFAULT_RETRIEVAL_PROCESSOR.tokenizer_name == "unicode-nfkc-casefold-word"
    assert DEFAULT_RETRIEVAL_PROCESSOR.unicode_version


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"k1": 0}, "positive finite"),
        ({"k1": float("nan")}, "positive finite"),
        ({"b": -0.1}, "0 to 1"),
        ({"b": True}, "0 to 1"),
        ({"top_k": 0}, "1 to 1000"),
        ({"top_k": 1001}, "1 to 1000"),
        ({"limits": "limits"}, "RetrievalLimits"),
    ],
)
def test_retrieval_configuration_rejects_invalid_values(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        RetrievalConfig(**changes)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["max_query_characters", "max_query_tokens"])
def test_retrieval_limits_require_positive_integers(field: str) -> None:
    values: dict[str, object] = {
        "max_query_characters": 1,
        "max_query_tokens": 1,
    }
    values[field] = 0
    with pytest.raises(ValueError, match="positive integer"):
        RetrievalLimits(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "other"}, "processor name"),
        ({"version": ""}, "processor version"),
        ({"tokenizer_name": "other"}, "tokenizer name"),
        ({"tokenizer_version": ""}, "tokenizer version"),
        ({"unicode_version": ""}, "Unicode version"),
    ],
)
def test_processor_descriptor_rejects_invalid_contract(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        RetrievalProcessorDescriptor(**changes)  # type: ignore[arg-type]


def test_result_dataset_and_evaluation_round_trip_canonical_json() -> None:
    corpus = _corpus()
    result = rank_corpus(corpus, "beta")
    dataset = create_retrieval_dataset(
        corpus.artifact_id,
        (RetrievalJudgment("q1", "beta", (corpus.chunks[1].chunk_id,)),),
    )
    evaluation = evaluate_retrieval(corpus, dataset)

    result_data = serialize_retrieval_result(result)
    dataset_data = serialize_retrieval_dataset(dataset)
    evaluation_data = serialize_retrieval_evaluation(evaluation)

    assert deserialize_retrieval_result(result_data) == result
    assert deserialize_retrieval_dataset(dataset_data) == dataset
    assert deserialize_retrieval_evaluation(evaluation_data) == evaluation
    assert result_data.endswith(b"\n")
    assert dataset_data.endswith(b"\n")
    assert evaluation_data.endswith(b"\n")
    assert is_retrieval_result_id(result.result_id)
    assert is_retrieval_dataset_id(dataset.dataset_id)
    assert is_retrieval_evaluation_id(evaluation.evaluation_id)


def test_result_identity_changes_with_query_configuration_and_unicode_version() -> None:
    corpus = _corpus()
    baseline = rank_corpus(corpus, "beta")
    changed_query = rank_corpus(corpus, "Beta")
    changed_config = rank_corpus(corpus, "beta", configuration=RetrievalConfig(top_k=1))
    changed_processor = rank_corpus(
        corpus,
        "beta",
        processor=RetrievalProcessorDescriptor(unicode_version="future"),
    )

    assert (
        len(
            {
                baseline.result_id,
                changed_query.result_id,
                changed_config.result_id,
                changed_processor.result_id,
            }
        )
        == 4
    )


def test_hit_and_result_models_reject_contradictions() -> None:
    result = rank_corpus(_corpus(), "beta")
    hit = result.hits[0]
    with pytest.raises(ValueError, match="positive finite"):
        replace(hit, score=0)
    with pytest.raises(ValueError, match="chunk_id"):
        replace(hit, chunk_id="bad")
    with pytest.raises(ValueError, match="matched_terms"):
        replace(hit, matched_terms=("beta", "beta"))
    with pytest.raises(ValueError, match="match hit text"):
        replace(hit, text="changed")
    with pytest.raises(ValueError, match="query_fingerprint"):
        replace(result, query_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="versioned tokenizer"):
        replace(result, query_tokens=("changed",))
    with pytest.raises(ValueError, match="returned_hit_count"):
        replace(result, returned_hit_count=0)
    with pytest.raises(ValueError, match="content_fingerprint"):
        replace(result, content_fingerprint="0" * 64)
    changed_hits = (replace(hit, rank=2), *result.hits[1:])
    with pytest.raises(ValueError, match="contiguous"):
        replace(
            result,
            hits=changed_hits,
            content_fingerprint=retrieval_content_fingerprint_for(changed_hits),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"rank": 0}, "rank"),
        ({"chunk_content_fingerprint": "bad"}, "SHA-256"),
        ({"dimension_unit": "points"}, "points or pixels"),
        ({"coordinate_origin": "top_left"}, "top_left"),
        ({"bounding_box": "box"}, "BoundingBox"),
        ({"text": ""}, "text must not be empty"),
        ({"matched_terms": []}, "immutable tuple"),
        ({"matched_terms": ("",)}, "non-empty strings"),
    ],
)
def test_hit_rejects_invalid_shape(changes: dict[str, object], message: str) -> None:
    hit = rank_corpus(_corpus(), "beta").hits[0]
    with pytest.raises(ValueError, match=message):
        replace(hit, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema_version": 2}, "schema version"),
        ({"result_id": "bad"}, "result_id"),
        ({"document_fingerprint": "bad"}, "document_fingerprint"),
        ({"document_id": f"sha256-{'0' * 64}"}, "document_id"),
        ({"source_corpus_artifact_id": "bad"}, "source_corpus_artifact_id"),
        ({"source_corpus_content_fingerprint": "bad"}, "source_corpus_content"),
        ({"query": " "}, "non-whitespace"),
        ({"query_tokens": []}, "immutable tuple"),
        ({"query_tokens": ("",)}, "non-empty strings"),
        ({"corpus_chunk_count": -1}, "non-negative"),
        ({"hits": []}, "immutable tuple"),
    ],
)
def test_result_rejects_invalid_shape(changes: dict[str, object], message: str) -> None:
    result = rank_corpus(_corpus(), "beta")
    with pytest.raises(ValueError, match=message):
        replace(result, **changes)  # type: ignore[arg-type]


def test_result_rejects_hit_provenance_and_order_contradictions() -> None:
    result = rank_corpus(_corpus(), "beta")
    first, second = result.hits

    outside = replace(first, chunk_index=result.corpus_chunk_count + 1)
    with pytest.raises(ValueError, match="exceeds corpus"):
        _replace_result_hits(result, (outside, second))

    wrong_page = replace(first, page_id="wrong")
    with pytest.raises(ValueError, match="page_id"):
        _replace_result_hits(result, (wrong_page, second))

    wrong_term = replace(first, matched_terms=("outside",))
    with pytest.raises(ValueError, match="query_tokens"):
        _replace_result_hits(result, (wrong_term, second))

    wrong_order = replace(second, score=first.score + 1)
    with pytest.raises(ValueError, match="descending score"):
        _replace_result_hits(result, (first, wrong_order))


def test_judgment_dataset_and_metrics_reject_invalid_contracts() -> None:
    corpus = _corpus()
    judgment = RetrievalJudgment("q1", "beta", (corpus.chunks[0].chunk_id,))
    dataset = create_retrieval_dataset(corpus.artifact_id, (judgment,))
    evaluation = evaluate_retrieval(corpus, dataset)
    with pytest.raises(ValueError, match="query_id"):
        replace(judgment, query_id="bad id")
    with pytest.raises(ValueError, match="unique"):
        replace(
            judgment,
            relevant_chunk_ids=(corpus.chunks[0].chunk_id, corpus.chunks[0].chunk_id),
        )
    with pytest.raises(ValueError, match="query IDs"):
        create_retrieval_dataset(corpus.artifact_id, (judgment, judgment))
    with pytest.raises(ValueError, match="dataset_id"):
        replace(dataset, dataset_id="bad")
    with pytest.raises(ValueError, match="counts"):
        replace(evaluation.cases[0], relevant_count=0)
    with pytest.raises(ValueError, match="mean_recall"):
        replace(evaluation, mean_recall=0.123)
    with pytest.raises(ValueError, match="content_fingerprint"):
        replace(evaluation, content_fingerprint="0" * 64)


def test_judgment_dataset_and_evaluation_reject_invalid_shapes() -> None:
    corpus = _corpus()
    judgment = RetrievalJudgment("q1", "beta", (corpus.chunks[0].chunk_id,))
    dataset = create_retrieval_dataset(corpus.artifact_id, (judgment,))
    evaluation = evaluate_retrieval(corpus, dataset)
    metric = evaluation.cases[0]

    with pytest.raises(ValueError, match="non-whitespace"):
        replace(judgment, query=" ")
    with pytest.raises(ValueError, match="immutable tuple"):
        replace(judgment, relevant_chunk_ids=[])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="canonical chunk"):
        replace(judgment, relevant_chunk_ids=("bad",))
    with pytest.raises(ValueError, match="schema version"):
        replace(dataset, schema_version=2)
    with pytest.raises(ValueError, match="source_corpus_artifact_id"):
        replace(dataset, source_corpus_artifact_id="bad")
    with pytest.raises(ValueError, match="non-empty immutable"):
        replace(dataset, cases=())
    with pytest.raises(ValueError, match="query_id"):
        replace(metric, query_id="bad id")
    with pytest.raises(ValueError, match="non-negative"):
        replace(metric, retrieved_count=-1)
    with pytest.raises(ValueError, match="0 to 1"):
        replace(metric, ndcg=1.1)
    with pytest.raises(ValueError, match="schema version"):
        replace(evaluation, schema_version=2)
    with pytest.raises(ValueError, match="evaluation_id"):
        replace(evaluation, evaluation_id="bad")
    with pytest.raises(ValueError, match="case_count"):
        replace(evaluation, case_count=2)


def _replace_result_hits(
    result: RetrievalResult, hits: tuple[RetrievalHit, ...]
) -> RetrievalResult:
    return replace(
        result,
        hits=hits,
        content_fingerprint=retrieval_content_fingerprint_for(hits),
    )


@pytest.mark.parametrize(
    ("kind", "deserialize", "serialize"),
    [
        ("result", deserialize_retrieval_result, serialize_retrieval_result),
        ("dataset", deserialize_retrieval_dataset, serialize_retrieval_dataset),
        ("evaluation", deserialize_retrieval_evaluation, serialize_retrieval_evaluation),
    ],
)
def test_deserializers_reject_invalid_json_and_unknown_fields(
    kind: str, deserialize: object, serialize: object
) -> None:
    corpus = _corpus()
    dataset = create_retrieval_dataset(
        corpus.artifact_id,
        (RetrievalJudgment("q1", "beta", (corpus.chunks[0].chunk_id,)),),
    )
    values = {
        "result": rank_corpus(corpus, "beta"),
        "dataset": dataset,
        "evaluation": evaluate_retrieval(corpus, dataset),
    }
    with pytest.raises(RetrievalIntegrityError, match="UTF-8 JSON"):
        deserialize(b"not json")  # type: ignore[operator]
    payload = json.loads(serialize(values[kind]))  # type: ignore[operator]
    payload["unexpected"] = True
    with pytest.raises(RetrievalIntegrityError, match="fields are invalid"):
        deserialize(json.dumps(payload).encode())  # type: ignore[operator]


def test_deserializer_rejects_wrong_json_types() -> None:
    result = rank_corpus(_corpus(), "beta")
    payload = json.loads(serialize_retrieval_result(result))
    payload["hits"] = {}
    with pytest.raises(RetrievalIntegrityError, match="JSON array"):
        deserialize_retrieval_result(json.dumps(payload).encode())

    payload = json.loads(serialize_retrieval_result(result))
    payload["configuration"]["top_k"] = 1.5
    with pytest.raises(RetrievalIntegrityError, match="integer"):
        deserialize_retrieval_result(json.dumps(payload).encode())
