"""Domain errors raised by deterministic text extraction and artifact storage."""


class ExtractionError(Exception):
    """Base class for expected text-extraction failures."""


class ExtractionUnsupportedError(ExtractionError):
    """The stored document cannot be handled by this extraction stage."""


class ExtractionLimitError(ExtractionError):
    """Extracted output exceeded the configured resource policy."""


class ExtractionIntegrityError(ExtractionError):
    """A text artifact or its verified source failed an integrity check."""


class ExtractionStorageError(ExtractionError):
    """A text artifact could not be stored or loaded safely."""


class ExtractionProcessingError(ExtractionError):
    """A supported extractor failed instead of producing a routing result."""
