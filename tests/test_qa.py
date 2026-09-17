from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

import pagetrace.qa.processing as qa_processing
from pagetrace.corpus import build_corpus_artifact
from pagetrace.qa import (
    AbstentionReason,
    QaConfig,
    QaIntegrityError,
    QaProcessorDescriptor,
    QaStatus,
    answer_from_retrieval,
    answer_question,
    deserialize_qa_result,
    is_answer_id,
    sentence_spans,
    serialize_qa_result,
)
from pagetrace.qa.models import qa_content_fingerprint_for, text_fingerprint_for
from pagetrace.retrieval import RetrievalConfig, RetrievalResult, rank_corpus
from tests.test_corpus_models import _source


def test_answer_contains_only_exact_ranked_evidence() -> None:
    retrieval = _retrieve(
        (("Revenue grew 12%. Expenses fell.",), ("Revenue growth outlook improved.",)),
        "revenue growth",
    )

    result = answer_from_retrieval(
        retrieval,
        configuration=QaConfig(max_evidence_items=2, minimum_query_term_coverage=0.5),
    )

    assert result.status is QaStatus.ANSWERED
    assert result.abstention_reason is None
    assert result.answer is not None
    assert is_answer_id(result.answer_id)
    assert result.answer == result.configuration.evidence_separator.join(
        citation.excerpt for citation in result.citations
    )
    assert result.citations[0].excerpt == "Revenue growth outlook improved."
    for citation in result.citations:
        hit = retrieval.hits[citation.retrieval_rank - 1]
        assert hit.text[citation.excerpt_start : citation.excerpt_end] == citation.excerpt


def test_answer_is_deterministic_and_character_limit_keeps_exact_slice() -> None:
    retrieval = _retrieve((("alpha trailing words",),), "alpha")
    configuration = QaConfig(max_answer_characters=5)

    first = answer_from_retrieval(retrieval, configuration=configuration)
    second = answer_from_retrieval(retrieval, configuration=configuration)

    assert first == second
    assert first.answer == "alpha"
    assert first.citations[0].excerpt_start == 0
    assert first.citations[0].excerpt_end == 5


def test_abstains_for_no_hits_weak_coverage_and_unusable_length() -> None:
    no_hits = answer_from_retrieval(_retrieve((("alpha",),), "missing"))
    weak = answer_from_retrieval(
        _retrieve((("alpha only",),), "alpha beta gamma"),
        configuration=QaConfig(minimum_query_term_coverage=0.5),
    )
    limited = answer_from_retrieval(
        _retrieve((("prefix alpha",),), "alpha"),
        configuration=QaConfig(max_answer_characters=3),
    )

    assert no_hits.status is QaStatus.ABSTAINED
    assert no_hits.abstention_reason is AbstentionReason.NO_RETRIEVAL_HITS
    assert weak.abstention_reason is AbstentionReason.INSUFFICIENT_QUERY_TERM_COVERAGE
    assert limited.abstention_reason is AbstentionReason.ANSWER_CHARACTER_LIMIT
    for result in (no_hits, weak, limited):
        assert result.answer is None
        assert result.answer_fingerprint is None
        assert result.citations == ()


def test_sentence_segmenter_preserves_exact_trimmed_offsets() -> None:
    text = "  First sentence.  Second?\r\nThird line\n\nFinal!  "
    spans = sentence_spans(text)

    assert tuple(text[start:end] for start, end in spans) == (
        "First sentence.",
        "Second?",
        "Third line",
        "Final!",
    )
    assert sentence_spans("   \n\r\n") == ()
    with pytest.raises(ValueError, match="string"):
        sentence_spans(1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: QaConfig(max_evidence_items=0), "max_evidence_items"),
        (lambda: QaConfig(max_answer_characters=100_001), "max_answer_characters"),
        (lambda: QaConfig(minimum_query_term_coverage=0), "minimum_query_term_coverage"),
        (lambda: QaConfig(evidence_separator=""), "evidence_separator"),
        (lambda: QaConfig(evidence_separator="x" * 11), "at most 10"),
    ],
)
def test_qa_configuration_validation(factory: Callable[[], QaConfig], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_valid_qa_configuration_is_immutable() -> None:
    configuration = QaConfig(max_evidence_items=1)
    assert configuration.max_evidence_items == 1


def test_qa_serialization_round_trip_is_canonical_and_strict() -> None:
    result = answer_from_retrieval(_retrieve((("alpha answer.",),), "alpha"))
    encoded = serialize_qa_result(result)

    assert deserialize_qa_result(encoded) == result
    assert serialize_qa_result(deserialize_qa_result(encoded)) == encoded
    assert json.loads(encoded)["retrieval"]["result_id"] == result.retrieval.result_id

    with pytest.raises(QaIntegrityError, match="strict UTF-8 JSON"):
        deserialize_qa_result(b"\xff")
    with pytest.raises(QaIntegrityError, match="strict UTF-8 JSON"):
        deserialize_qa_result(b'{"schema_version":1,"schema_version":1}')
    with pytest.raises(QaIntegrityError, match="fields do not match"):
        deserialize_qa_result(b"{}")
    with pytest.raises(QaIntegrityError, match="bytes"):
        deserialize_qa_result("{}")  # type: ignore[arg-type]


def test_deserialization_rejects_tampering_and_nonfinite_numbers() -> None:
    result = answer_from_retrieval(_retrieve((("alpha answer.",),), "alpha"))
    payload = json.loads(serialize_qa_result(result))
    payload["answer"] = "invented"
    with pytest.raises(QaIntegrityError, match="invalid QA result value"):
        deserialize_qa_result(json.dumps(payload).encode())

    data = serialize_qa_result(result).replace(
        b'"query_term_coverage":1.0', b'"query_term_coverage":NaN'
    )
    with pytest.raises(QaIntegrityError, match="strict UTF-8 JSON"):
        deserialize_qa_result(data)


def test_result_validation_rejects_citation_not_present_in_retrieved_chunk() -> None:
    result = answer_from_retrieval(_retrieve((("alpha answer.",),), "alpha"))
    citation = result.citations[0]
    tampered_excerpt = citation.excerpt[1:]
    tampered_citation = replace(
        citation,
        excerpt_start=1,
        excerpt=tampered_excerpt,
        excerpt_fingerprint=text_fingerprint_for(tampered_excerpt),
        matched_terms=("alpha",),
        query_term_coverage=1.0,
    )
    citations = (tampered_citation,)
    answer = tampered_excerpt

    with pytest.raises(ValueError, match="matched_terms"):
        replace(
            result,
            answer=answer,
            answer_fingerprint=text_fingerprint_for(answer),
            citations=citations,
            content_fingerprint=qa_content_fingerprint_for(
                QaStatus.ANSWERED, None, answer, citations
            ),
        )


def test_model_rejects_invalid_processor_and_contradictory_abstention() -> None:
    retrieval = _retrieve((("alpha",),), "alpha")
    answered = answer_from_retrieval(retrieval)
    with pytest.raises(ValueError, match="processor name"):
        QaProcessorDescriptor(name="other")
    with pytest.raises(ValueError, match="agree with retrieval hit availability"):
        replace(
            answered,
            status=QaStatus.ABSTAINED,
            abstention_reason=AbstentionReason.NO_RETRIEVAL_HITS,
            answer=None,
            answer_fingerprint=None,
            citations=(),
            content_fingerprint=qa_content_fingerprint_for(
                QaStatus.ABSTAINED, AbstentionReason.NO_RETRIEVAL_HITS, None, ()
            ),
        )


def test_deserialization_wraps_invalid_source_retrieval() -> None:
    result = answer_from_retrieval(_retrieve((("alpha",),), "alpha"))
    payload = json.loads(serialize_qa_result(result))
    payload["retrieval"]["content_fingerprint"] = "0" * 64

    with pytest.raises(QaIntegrityError, match="invalid source retrieval result"):
        deserialize_qa_result(json.dumps(payload).encode())


def test_public_answer_question_uses_retrieval_configuration_and_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retrieval = _retrieve((("alpha",),), "alpha", top_k=1)
    captured: dict[str, object] = {}

    def fake_retrieve(*args: object, **kwargs: object) -> object:
        captured["args"] = args
        captured.update(kwargs)
        return retrieval

    monkeypatch.setattr(qa_processing, "retrieve", fake_retrieve)
    result = answer_question(
        retrieval.document_id,
        retrieval.source_corpus_artifact_id,
        "alpha",
        store=tmp_path,
        retrieval_configuration=RetrievalConfig(top_k=1),
    )

    assert result.answer == "alpha"
    assert captured["store"] == tmp_path.resolve()
    assert captured["configuration"] == RetrievalConfig(top_k=1)


def _retrieve(
    texts_by_page: tuple[tuple[str, ...], ...], query: str, *, top_k: int = 10
) -> RetrievalResult:
    corpus = build_corpus_artifact(_source(texts_by_page))
    return rank_corpus(corpus, query, configuration=RetrievalConfig(top_k=top_k))
