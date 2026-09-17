"""Public orchestration for evidence-grounded QA over stored corpora."""

from pathlib import Path

from pagetrace.qa.grounding import answer_from_retrieval
from pagetrace.qa.models import DEFAULT_QA_CONFIG, QaConfig, QaResult
from pagetrace.retrieval import DEFAULT_RETRIEVAL_CONFIG, RetrievalConfig, retrieve


def answer_question(
    document_id: str,
    corpus_artifact_id: str,
    question: str,
    *,
    store: Path,
    retrieval_configuration: RetrievalConfig = DEFAULT_RETRIEVAL_CONFIG,
    configuration: QaConfig = DEFAULT_QA_CONFIG,
) -> QaResult:
    """Retrieve verified evidence and produce an extractive answer or abstention."""

    retrieval = retrieve(
        document_id,
        corpus_artifact_id,
        question,
        store=Path(store).expanduser().resolve(),
        configuration=retrieval_configuration,
    )
    return answer_from_retrieval(retrieval, configuration=configuration)
