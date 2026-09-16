from __future__ import annotations

import json

import pytest

from pagetrace.ocr import evaluate_ocr, serialize_ocr_evaluation


def test_exact_ocr_evaluation_has_zero_error() -> None:
    evaluation = evaluate_ocr("PageTrace text", "PageTrace text")

    assert evaluation.exact_match is True
    assert evaluation.character_edits == 0
    assert evaluation.character_error_rate == 0
    assert evaluation.word_edits == 0
    assert evaluation.word_error_rate == 0


def test_ocr_evaluation_reports_character_and_word_edits_without_normalization() -> None:
    evaluation = evaluate_ocr("cat sat", "cut sits")

    assert evaluation.exact_match is False
    assert evaluation.character_edits == 3
    assert evaluation.reference_character_count == 7
    assert evaluation.character_error_rate == pytest.approx(3 / 7)
    assert evaluation.word_edits == 2
    assert evaluation.reference_word_count == 2
    assert evaluation.word_error_rate == 1


@pytest.mark.parametrize(
    ("reference", "prediction", "expected"),
    [("", "", 0.0), ("", "unexpected", 1.0)],
)
def test_empty_reference_error_rate_is_explicit(
    reference: str, prediction: str, expected: float
) -> None:
    evaluation = evaluate_ocr(reference, prediction)

    assert evaluation.character_error_rate == expected
    assert evaluation.word_error_rate == expected


def test_evaluation_serialization_is_stable_json() -> None:
    first = serialize_ocr_evaluation(evaluate_ocr("one two", "one too"))
    second = serialize_ocr_evaluation(evaluate_ocr("one two", "one too"))
    payload = json.loads(first)

    assert first == second
    assert first.endswith(b"\n")
    assert payload["character_edits"] == 1
    assert payload["word_edits"] == 1


def test_evaluation_rejects_non_string_inputs() -> None:
    with pytest.raises(TypeError, match="strings"):
        evaluate_ocr("reference", 7)  # type: ignore[arg-type]
