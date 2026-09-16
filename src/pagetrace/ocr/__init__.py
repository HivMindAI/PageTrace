"""Public API for routed OCR processing and transparent evaluation."""

from pagetrace.ocr.errors import (
    OcrDependencyError,
    OcrError,
    OcrEvaluationError,
    OcrIntegrityError,
    OcrLimitError,
    OcrProcessingError,
    OcrStorageError,
)
from pagetrace.ocr.evaluation import OcrEvaluation, evaluate_ocr, serialize_ocr_evaluation
from pagetrace.ocr.models import (
    DEFAULT_OCR_CONFIG,
    DEFAULT_OCR_LIMITS,
    OCR_SCHEMA_VERSION,
    OcrArtifact,
    OcrConfig,
    OcrLimits,
    OcrMethod,
    OcrPageResult,
    OcrPageStatus,
    OcrProcessorDescriptor,
    OcrRoutingPolicy,
    is_ocr_artifact_id,
    ocr_artifact_id_for,
    ocr_content_fingerprint_for,
)
from pagetrace.ocr.processing import ocr_document
from pagetrace.ocr.serialization import deserialize_ocr_artifact, serialize_ocr_artifact
from pagetrace.ocr.storage import load_ocr_artifact

__all__ = [
    "DEFAULT_OCR_CONFIG",
    "DEFAULT_OCR_LIMITS",
    "OCR_SCHEMA_VERSION",
    "OcrArtifact",
    "OcrConfig",
    "OcrDependencyError",
    "OcrError",
    "OcrEvaluation",
    "OcrEvaluationError",
    "OcrIntegrityError",
    "OcrLimitError",
    "OcrLimits",
    "OcrMethod",
    "OcrPageResult",
    "OcrPageStatus",
    "OcrProcessingError",
    "OcrProcessorDescriptor",
    "OcrRoutingPolicy",
    "OcrStorageError",
    "deserialize_ocr_artifact",
    "evaluate_ocr",
    "is_ocr_artifact_id",
    "load_ocr_artifact",
    "ocr_artifact_id_for",
    "ocr_content_fingerprint_for",
    "ocr_document",
    "serialize_ocr_artifact",
    "serialize_ocr_evaluation",
]
