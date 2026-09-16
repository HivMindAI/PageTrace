"""Small, transparent OCR accuracy metrics without text normalization."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OcrEvaluation:
    """Exact-text, character-error-rate, and word-error-rate measurements."""

    exact_match: bool
    character_edits: int
    reference_character_count: int
    character_error_rate: float
    word_edits: int
    reference_word_count: int
    word_error_rate: float


def evaluate_ocr(reference: str, prediction: str) -> OcrEvaluation:
    """Evaluate prediction against reference exactly, with no hidden normalization."""

    if not isinstance(reference, str) or not isinstance(prediction, str):
        raise TypeError("reference and prediction must be strings")
    character_edits = _levenshtein(tuple(reference), tuple(prediction))
    reference_words = tuple(reference.split())
    prediction_words = tuple(prediction.split())
    word_edits = _levenshtein(reference_words, prediction_words)
    return OcrEvaluation(
        exact_match=reference == prediction,
        character_edits=character_edits,
        reference_character_count=len(reference),
        character_error_rate=_error_rate(character_edits, len(reference)),
        word_edits=word_edits,
        reference_word_count=len(reference_words),
        word_error_rate=_error_rate(word_edits, len(reference_words)),
    )


def serialize_ocr_evaluation(evaluation: OcrEvaluation) -> bytes:
    """Serialize evaluation metrics as stable UTF-8 JSON for CLI automation."""

    payload = {
        "character_edits": evaluation.character_edits,
        "character_error_rate": evaluation.character_error_rate,
        "exact_match": evaluation.exact_match,
        "reference_character_count": evaluation.reference_character_count,
        "reference_word_count": evaluation.reference_word_count,
        "word_edits": evaluation.word_edits,
        "word_error_rate": evaluation.word_error_rate,
    }
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _error_rate(edits: int, reference_length: int) -> float:
    if reference_length == 0:
        return 0.0 if edits == 0 else 1.0
    return edits / reference_length


def _levenshtein(reference: tuple[str, ...], prediction: tuple[str, ...]) -> int:
    previous = list(range(len(prediction) + 1))
    for reference_index, reference_item in enumerate(reference, start=1):
        current = [reference_index]
        for prediction_index, prediction_item in enumerate(prediction, start=1):
            substitution = previous[prediction_index - 1] + (reference_item != prediction_item)
            current.append(min(previous[prediction_index] + 1, current[-1] + 1, substitution))
        previous = current
    return previous[-1]
