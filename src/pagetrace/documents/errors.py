"""Domain errors raised by document ingestion and storage."""


class DocumentError(Exception):
    """Base class for expected document-domain failures."""


class UnsupportedDocumentError(DocumentError):
    """The input is not one of PageTrace's supported document formats."""


class InvalidDocumentError(DocumentError):
    """The input claims a supported format but is invalid or unsafe."""


class DocumentLimitError(DocumentError):
    """A configured ingestion resource limit was exceeded."""


class EncryptedDocumentError(InvalidDocumentError):
    """An encrypted PDF was supplied where plaintext input is required."""


class DocumentStorageError(DocumentError):
    """A document artifact could not be stored or loaded."""


class DocumentIntegrityError(DocumentStorageError):
    """A persisted document artifact failed an integrity check."""
