"""Public evidence-grounded question-answering API."""

from pagetrace.qa.errors import QaError, QaIntegrityError
from pagetrace.qa.grounding import answer_from_retrieval, sentence_spans
from pagetrace.qa.models import (
    DEFAULT_QA_CONFIG,
    DEFAULT_QA_PROCESSOR,
    QA_PROCESSOR_NAME,
    QA_PROCESSOR_VERSION,
    QA_SCHEMA_VERSION,
    SENTENCE_SEGMENTER_NAME,
    SENTENCE_SEGMENTER_VERSION,
    AbstentionReason,
    EvidenceCitation,
    QaConfig,
    QaProcessorDescriptor,
    QaResult,
    QaStatus,
    answer_id_for,
    is_answer_id,
)
from pagetrace.qa.processing import answer_question
from pagetrace.qa.serialization import deserialize_qa_result, serialize_qa_result

__all__ = [
    "DEFAULT_QA_CONFIG",
    "DEFAULT_QA_PROCESSOR",
    "QA_PROCESSOR_NAME",
    "QA_PROCESSOR_VERSION",
    "QA_SCHEMA_VERSION",
    "SENTENCE_SEGMENTER_NAME",
    "SENTENCE_SEGMENTER_VERSION",
    "AbstentionReason",
    "EvidenceCitation",
    "QaConfig",
    "QaError",
    "QaIntegrityError",
    "QaProcessorDescriptor",
    "QaResult",
    "QaStatus",
    "answer_from_retrieval",
    "answer_id_for",
    "answer_question",
    "deserialize_qa_result",
    "is_answer_id",
    "sentence_spans",
    "serialize_qa_result",
]
