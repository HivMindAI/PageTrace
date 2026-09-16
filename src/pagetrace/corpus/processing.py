"""Public orchestration for deterministic corpus construction."""

from pathlib import Path

from pagetrace.corpus.chunking import build_corpus_artifact
from pagetrace.corpus.models import DEFAULT_CORPUS_CONFIG, CorpusArtifact, CorpusConfig
from pagetrace.corpus.storage import persist_corpus_artifact
from pagetrace.structure import load_structured_document


def build_corpus(
    document_id: str,
    structure_artifact_id: str,
    *,
    store: Path,
    configuration: CorpusConfig = DEFAULT_CORPUS_CONFIG,
) -> CorpusArtifact:
    """Build and atomically persist chunks from one verified structure artifact."""

    normalized_store = Path(store).expanduser().resolve()
    source = load_structured_document(
        structure_artifact_id,
        document_id=document_id,
        store=normalized_store,
    )
    artifact = build_corpus_artifact(source, configuration=configuration)
    return persist_corpus_artifact(artifact, store=normalized_store)
