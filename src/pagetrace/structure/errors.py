"""Typed failures for deterministic structured document representation."""


class StructureError(Exception):
    """Base class for expected structured-document failures."""


class StructureDependencyError(StructureError):
    """An optional layout dependency is unavailable or incompatible."""


class StructureLimitError(StructureError):
    """Structured output exceeded an explicit configured resource bound."""


class StructureProcessingError(StructureError):
    """A verified source could not be converted into structured output."""


class StructureIntegrityError(StructureError):
    """Persisted structure or its provenance failed validation."""


class StructureStorageError(StructureError):
    """Structured artifact persistence or readback failed."""
