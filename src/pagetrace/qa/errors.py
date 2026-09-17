"""Domain errors for evidence-grounded question answering."""


class QaError(Exception):
    """Base class for expected question-answering failures."""


class QaIntegrityError(QaError):
    """Raised when answer evidence or serialized data is contradictory."""
