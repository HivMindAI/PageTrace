"""Expected failures at the PageTrace product-backend boundary."""


class BackendError(Exception):
    """Base class for expected backend failures."""


class BackendConfigurationError(BackendError):
    """Raised for unsafe or contradictory backend configuration."""


class BackendInputError(BackendError):
    """Raised for malformed or oversized API/workflow input."""


class BackendNotFoundError(BackendError):
    """Raised when a requested backend resource does not exist."""


class BackendConflictError(BackendError):
    """Raised for idempotency or state-transition conflicts."""


class BackendCapacityError(BackendError):
    """Raised when an operational queue or storage limit is reached."""


class BackendPersistenceError(BackendError):
    """Raised when durable backend state cannot be safely read or written."""


class WorkflowFailure(BackendError):
    """A handler failure safe to expose as a stable job error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
