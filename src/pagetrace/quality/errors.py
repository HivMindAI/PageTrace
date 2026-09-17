"""Domain errors for the consolidated quality system."""


class QualityError(Exception):
    """Base class for expected quality-system failures."""


class QualityIntegrityError(QualityError):
    """Raised when a quality suite or report is contradictory."""


class QualityInputError(QualityError):
    """Raised when evaluation inputs cannot form a meaningful report."""
