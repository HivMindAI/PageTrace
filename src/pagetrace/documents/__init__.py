"""Public API for deterministic PageTrace document ingestion."""

from pagetrace.documents.errors import (
    DocumentError,
    DocumentIntegrityError,
    DocumentLimitError,
    DocumentStorageError,
    EncryptedDocumentError,
    InvalidDocumentError,
    UnsupportedDocumentError,
)
from pagetrace.documents.ingestion import ingest_document
from pagetrace.documents.manifest import deserialize_manifest, serialize_manifest
from pagetrace.documents.models import (
    DEFAULT_INGESTION_LIMITS,
    DimensionUnit,
    DocumentManifest,
    DocumentMetadata,
    IngestionLimits,
    MediaType,
    PageManifest,
)
from pagetrace.documents.storage import load_document

__all__ = [
    "DEFAULT_INGESTION_LIMITS",
    "DimensionUnit",
    "DocumentError",
    "DocumentIntegrityError",
    "DocumentLimitError",
    "DocumentManifest",
    "DocumentMetadata",
    "DocumentStorageError",
    "EncryptedDocumentError",
    "IngestionLimits",
    "InvalidDocumentError",
    "MediaType",
    "PageManifest",
    "UnsupportedDocumentError",
    "deserialize_manifest",
    "ingest_document",
    "load_document",
    "serialize_manifest",
]
