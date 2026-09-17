"""Domain errors for deterministic lexical retrieval and evaluation."""


class RetrievalError(Exception):
    """Base class for expected retrieval failures."""


class RetrievalIntegrityError(RetrievalError):
    """Raised when retrieval data or provenance is contradictory."""


class RetrievalLimitError(RetrievalError):
    """Raised when a bounded retrieval input limit is exceeded."""


class RetrievalQueryError(RetrievalError):
    """Raised when a query cannot produce lexical terms."""


class RetrievalEvaluationError(RetrievalError):
    """Raised when an evaluation dataset is invalid for a corpus."""
