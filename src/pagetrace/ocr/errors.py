"""Domain errors raised by PageTrace OCR processing and evaluation."""


class OcrError(Exception):
    """Base class for expected OCR-stage failures."""


class OcrDependencyError(OcrError):
    """The optional OCR runtime is unavailable or incomplete."""


class OcrLimitError(OcrError):
    """OCR input or output exceeded the configured resource policy."""


class OcrProcessingError(OcrError):
    """A renderer or OCR backend failed on an otherwise supported document."""


class OcrIntegrityError(OcrError):
    """An OCR artifact or one of its provenance links failed validation."""


class OcrStorageError(OcrError):
    """An OCR artifact could not be stored or loaded safely."""


class OcrEvaluationError(OcrError):
    """OCR evaluation input could not be read or evaluated safely."""
