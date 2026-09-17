"""Public orchestration for retrieval against verified stored corpora."""

from pathlib import Path

from pagetrace.corpus import load_corpus_artifact
from pagetrace.retrieval.lexical import rank_corpus
from pagetrace.retrieval.models import DEFAULT_RETRIEVAL_CONFIG, RetrievalConfig, RetrievalResult


def retrieve(
    document_id: str,
    corpus_artifact_id: str,
    query: str,
    *,
    store: Path,
    configuration: RetrievalConfig = DEFAULT_RETRIEVAL_CONFIG,
) -> RetrievalResult:
    """Load a fully verified corpus and return deterministic BM25 results."""

    corpus = load_corpus_artifact(
        corpus_artifact_id,
        document_id=document_id,
        store=Path(store).expanduser().resolve(),
    )
    return rank_corpus(corpus, query, configuration=configuration)
