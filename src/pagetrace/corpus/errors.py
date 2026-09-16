"""Domain errors for deterministic corpus construction."""


class CorpusError(Exception):
    """Base class for expected corpus failures."""


class CorpusIntegrityError(CorpusError):
    """Raised when a corpus artifact or its provenance is contradictory."""


class CorpusLimitError(CorpusError):
    """Raised when bounded corpus construction limits are exceeded."""


class CorpusStorageError(CorpusError):
    """Raised when a corpus artifact cannot be safely persisted or loaded."""
