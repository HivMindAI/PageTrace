"""Public API for deterministic embedded text extraction and OCR routing."""

from pagetrace.extraction.errors import (
    ExtractionError,
    ExtractionIntegrityError,
    ExtractionLimitError,
    ExtractionProcessingError,
    ExtractionStorageError,
    ExtractionUnsupportedError,
)
from pagetrace.extraction.extraction import extract_document_text
from pagetrace.extraction.models import (
    DEFAULT_EXTRACTION_LIMITS,
    DEFAULT_TEXT_EXTRACTION_CONFIG,
    EXTRACTION_SCHEMA_VERSION,
    ExtractionLimits,
    ExtractionMethod,
    ExtractorDescriptor,
    PageTextResult,
    PageTextStatus,
    PdfExtractionMode,
    TextExtractionArtifact,
    TextExtractionConfig,
)
from pagetrace.extraction.serialization import (
    deserialize_text_extraction,
    serialize_text_extraction,
)
from pagetrace.extraction.storage import load_text_extraction

__all__ = [
    "DEFAULT_EXTRACTION_LIMITS",
    "DEFAULT_TEXT_EXTRACTION_CONFIG",
    "EXTRACTION_SCHEMA_VERSION",
    "ExtractionError",
    "ExtractionIntegrityError",
    "ExtractionLimitError",
    "ExtractionLimits",
    "ExtractionMethod",
    "ExtractionProcessingError",
    "ExtractionStorageError",
    "ExtractionUnsupportedError",
    "ExtractorDescriptor",
    "PageTextResult",
    "PageTextStatus",
    "PdfExtractionMode",
    "TextExtractionArtifact",
    "TextExtractionConfig",
    "deserialize_text_extraction",
    "extract_document_text",
    "load_text_extraction",
    "serialize_text_extraction",
]
