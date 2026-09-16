"""Public API for deterministic, provenance-aware corpus construction."""

from pagetrace.corpus.chunking import build_corpus_artifact
from pagetrace.corpus.errors import (
    CorpusError,
    CorpusIntegrityError,
    CorpusLimitError,
    CorpusStorageError,
)
from pagetrace.corpus.models import (
    CORPUS_PROCESSOR_NAME,
    CORPUS_PROCESSOR_VERSION,
    CORPUS_SCHEMA_VERSION,
    DEFAULT_CORPUS_CONFIG,
    DEFAULT_CORPUS_LIMITS,
    DEFAULT_CORPUS_PROCESSOR,
    ChunkFragment,
    ChunkRecord,
    CorpusArtifact,
    CorpusConfig,
    CorpusLimits,
    CorpusProcessorDescriptor,
    chunk_id_for,
    corpus_artifact_id_for,
    corpus_content_fingerprint_for,
    is_chunk_id,
    is_corpus_artifact_id,
)
from pagetrace.corpus.processing import build_corpus
from pagetrace.corpus.serialization import deserialize_corpus_artifact, serialize_corpus_artifact
from pagetrace.corpus.storage import load_corpus_artifact

__all__ = [
    "CORPUS_PROCESSOR_NAME",
    "CORPUS_PROCESSOR_VERSION",
    "CORPUS_SCHEMA_VERSION",
    "DEFAULT_CORPUS_CONFIG",
    "DEFAULT_CORPUS_LIMITS",
    "DEFAULT_CORPUS_PROCESSOR",
    "ChunkFragment",
    "ChunkRecord",
    "CorpusArtifact",
    "CorpusConfig",
    "CorpusError",
    "CorpusIntegrityError",
    "CorpusLimitError",
    "CorpusLimits",
    "CorpusProcessorDescriptor",
    "CorpusStorageError",
    "build_corpus",
    "build_corpus_artifact",
    "chunk_id_for",
    "corpus_artifact_id_for",
    "corpus_content_fingerprint_for",
    "deserialize_corpus_artifact",
    "is_chunk_id",
    "is_corpus_artifact_id",
    "load_corpus_artifact",
    "serialize_corpus_artifact",
]
