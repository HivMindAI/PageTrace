"""Reproducible evidence-backed portfolio demonstration for the v1.0 release."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pagetrace import __version__
from pagetrace.corpus import build_corpus
from pagetrace.documents import ingest_document
from pagetrace.extraction import extract_document_text
from pagetrace.ocr import OcrConfig, OcrRoutingPolicy, evaluate_ocr, ocr_document
from pagetrace.qa import QaConfig, QaResult, QaStatus, answer_question, serialize_qa_result
from pagetrace.quality import (
    AnswerQualityCase,
    MetricComparator,
    MetricGate,
    QualityMetricName,
    QualityPolicy,
    QualityReportStatus,
    create_quality_suite,
    evaluate_quality,
    serialize_quality_report,
    serialize_quality_suite,
    text_quality_case,
)
from pagetrace.retrieval import (
    RetrievalConfig,
    RetrievalJudgment,
    create_retrieval_dataset,
    evaluate_retrieval,
    serialize_retrieval_dataset,
    serialize_retrieval_evaluation,
)
from pagetrace.structure import structure_document

PORTFOLIO_SCHEMA_VERSION = 1
PORTFOLIO_SOURCE_NAME = "northstar-fy2025.pdf"
PORTFOLIO_MANIFEST_NAME = "portfolio-manifest.json"
PORTFOLIO_ANSWER_QUESTION = "Northstar FY2025 revenue?"
PORTFOLIO_ABSTENTION_QUESTION = "Carbon emissions target?"
PORTFOLIO_PAGE_TEXTS = (
    "Northstar FY2025 revenue was $12.4 million, up 24 percent year over year.",
    "Northstar FY2025 operating margin was 18 percent. Risks include supplier concentration.",
)
PORTFOLIO_LIMITATIONS = (
    "The demonstration is a two-page synthetic fixture, not a representative accuracy benchmark.",
    "Answers are extractive source excerpts and cannot synthesize across evidence.",
    "Retrieval is lexical BM25 without a persistent or vector index.",
    "Quality results apply only to the included deterministic cases.",
    "Document parsers and OCR dependencies still execute in-process without hard resource "
    "isolation.",
    "The built-in web service supports one trusted local operator and is not a remote "
    "multi-user service.",
)


class PortfolioDemoError(Exception):
    """Expected failure while preparing the bounded portfolio demonstration."""


@dataclass(frozen=True, slots=True)
class PortfolioDemoResult:
    """Stable identities and paths produced by one portfolio demonstration."""

    output_directory: Path
    manifest_path: Path
    document_id: str
    corpus_artifact_id: str
    answer_id: str
    abstention_id: str
    quality_report_id: str


def run_portfolio_demo(output_directory: Path) -> PortfolioDemoResult:
    """Run the complete deterministic portfolio workflow into a new atomic directory."""

    target = _new_output_target(output_directory)
    try:
        staging = Path(tempfile.mkdtemp(prefix=".pagetrace-portfolio-", dir=target.parent))
    except OSError as exc:
        raise PortfolioDemoError("portfolio staging directory could not be created") from exc
    try:
        result = _build_portfolio(staging)
        staging.replace(target)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise PortfolioDemoError("portfolio output could not be written atomically") from exc
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return PortfolioDemoResult(
        output_directory=target,
        manifest_path=target / PORTFOLIO_MANIFEST_NAME,
        document_id=result.document_id,
        corpus_artifact_id=result.corpus_artifact_id,
        answer_id=result.answer_id,
        abstention_id=result.abstention_id,
        quality_report_id=result.quality_report_id,
    )


def _build_portfolio(staging: Path) -> PortfolioDemoResult:
    source = staging / PORTFOLIO_SOURCE_NAME
    source.write_bytes(_portfolio_pdf_bytes(PORTFOLIO_PAGE_TEXTS))
    store = staging / "artifact-store"

    document = ingest_document(source, store=store)
    text = extract_document_text(document.document_id, store=store)
    ocr = ocr_document(
        document.document_id,
        text.artifact_id,
        store=store,
        configuration=OcrConfig(routing_policy=OcrRoutingPolicy.CANDIDATES_ONLY),
    )
    structured = structure_document(
        document.document_id,
        text.artifact_id,
        ocr.artifact_id,
        store=store,
    )
    corpus = build_corpus(document.document_id, structured.artifact_id, store=store)

    page_chunks = {
        page_number: tuple(
            chunk.chunk_id for chunk in corpus.chunks if chunk.page_number == page_number
        )
        for page_number in range(1, document.page_count + 1)
    }
    if any(not chunk_ids for chunk_ids in page_chunks.values()):
        raise PortfolioDemoError("portfolio corpus omitted evidence from a source page")

    retrieval_configuration = RetrievalConfig(top_k=1)
    dataset = create_retrieval_dataset(
        corpus.artifact_id,
        (
            RetrievalJudgment(
                "revenue",
                "Northstar FY2025 revenue",
                page_chunks[1],
            ),
            RetrievalJudgment(
                "operating-margin",
                "Northstar FY2025 operating margin",
                page_chunks[2],
            ),
        ),
    )
    retrieval_evaluation = evaluate_retrieval(
        corpus,
        dataset,
        configuration=retrieval_configuration,
    )

    qa_configuration = QaConfig(max_evidence_items=1, minimum_query_term_coverage=0.5)
    answer = answer_question(
        document.document_id,
        corpus.artifact_id,
        PORTFOLIO_ANSWER_QUESTION,
        store=store,
        retrieval_configuration=retrieval_configuration,
        configuration=qa_configuration,
    )
    abstention = answer_question(
        document.document_id,
        corpus.artifact_id,
        PORTFOLIO_ABSTENTION_QUESTION,
        store=store,
        retrieval_configuration=retrieval_configuration,
        configuration=qa_configuration,
    )
    if answer.status is not QaStatus.ANSWERED or answer.answer != PORTFOLIO_PAGE_TEXTS[0]:
        raise PortfolioDemoError("portfolio supported-answer expectation was not met")
    if abstention.status is not QaStatus.ABSTAINED:
        raise PortfolioDemoError("portfolio out-of-scope question did not abstain")

    text_cases = tuple(
        text_quality_case(
            f"embedded-page-{page.page_number}",
            evaluate_ocr(expected, page.text or ""),
        )
        for expected, page in zip(PORTFOLIO_PAGE_TEXTS, text.pages, strict=True)
    )
    suite = create_quality_suite(
        text_cases=text_cases,
        retrieval_evaluations=(retrieval_evaluation,),
        answer_cases=(
            AnswerQualityCase(
                "supported-revenue-answer",
                answer,
                QaStatus.ANSWERED,
                acceptable_answers=(PORTFOLIO_PAGE_TEXTS[0],),
                relevant_chunk_ids=page_chunks[1],
            ),
            AnswerQualityCase(
                "unsupported-carbon-question",
                abstention,
                QaStatus.ABSTAINED,
            ),
        ),
        policy=QualityPolicy(
            policy_id="portfolio-v1",
            gates=(
                MetricGate(
                    QualityMetricName.TEXT_EXACT_MATCH_RATE,
                    MetricComparator.AT_LEAST,
                    1.0,
                    minimum_samples=2,
                ),
                MetricGate(
                    QualityMetricName.RETRIEVAL_MEAN_RECALL,
                    MetricComparator.AT_LEAST,
                    1.0,
                    minimum_samples=2,
                ),
                MetricGate(
                    QualityMetricName.ANSWER_STATUS_ACCURACY,
                    MetricComparator.AT_LEAST,
                    1.0,
                    minimum_samples=2,
                ),
                MetricGate(
                    QualityMetricName.ANSWER_EXACT_MATCH_RATE,
                    MetricComparator.AT_LEAST,
                    1.0,
                ),
                MetricGate(
                    QualityMetricName.PROVENANCE_CITATION_PRECISION,
                    MetricComparator.AT_LEAST,
                    1.0,
                ),
                MetricGate(
                    QualityMetricName.PROVENANCE_CITATION_RECALL,
                    MetricComparator.AT_LEAST,
                    1.0,
                ),
                MetricGate(
                    QualityMetricName.SAFETY_FALSE_ANSWER_RATE,
                    MetricComparator.AT_MOST,
                    0.0,
                ),
                MetricGate(
                    QualityMetricName.COST_EXTERNAL_REQUESTS,
                    MetricComparator.AT_MOST,
                    0.0,
                    minimum_samples=2,
                ),
            ),
        ),
    )
    report = evaluate_quality(suite)
    if report.status is not QualityReportStatus.PASSED:
        raise PortfolioDemoError("portfolio quality gates did not pass")

    generated = {
        "retrieval-dataset.json": serialize_retrieval_dataset(dataset),
        "retrieval-evaluation.json": serialize_retrieval_evaluation(retrieval_evaluation),
        "qa-supported-answer.json": serialize_qa_result(answer),
        "qa-abstention.json": serialize_qa_result(abstention),
        "quality-suite.json": serialize_quality_suite(suite),
        "quality-report.json": serialize_quality_report(report),
    }
    for name, data in generated.items():
        (staging / name).write_bytes(data)

    files = {
        PORTFOLIO_SOURCE_NAME: _sha256_file(source),
        **{name: hashlib.sha256(data).hexdigest() for name, data in generated.items()},
    }
    summary = {
        "artifact_ids": {
            "corpus": corpus.artifact_id,
            "ocr": ocr.artifact_id,
            "structure": structured.artifact_id,
            "text": text.artifact_id,
        },
        "demonstrations": {
            "abstention": _qa_summary(abstention),
            "supported_answer": _qa_summary(answer),
        },
        "document": {
            "document_id": document.document_id,
            "fingerprint": document.fingerprint,
            "page_count": document.page_count,
            "source_file": PORTFOLIO_SOURCE_NAME,
        },
        "evaluation": {
            "quality": {
                "gates": [
                    {
                        "metric": result.gate.metric.value,
                        "observed_value": result.observed_value,
                        "status": result.status.value,
                        "threshold": result.gate.threshold,
                    }
                    for result in report.gates
                ],
                "metrics": {
                    observation.metric.value: {
                        "sample_count": observation.sample_count,
                        "value": observation.value,
                    }
                    for observation in report.metrics
                },
                "report_id": report.report_id,
                "status": report.status.value,
                "suite_id": suite.suite_id,
            },
            "retrieval": {
                "case_count": retrieval_evaluation.case_count,
                "dataset_id": dataset.dataset_id,
                "evaluation_id": retrieval_evaluation.evaluation_id,
                "mean_average_precision": retrieval_evaluation.mean_average_precision,
                "mean_ndcg": retrieval_evaluation.mean_ndcg,
                "mean_precision": retrieval_evaluation.mean_precision,
                "mean_recall": retrieval_evaluation.mean_recall,
                "mean_reciprocal_rank": retrieval_evaluation.mean_reciprocal_rank,
            },
        },
        "files": files,
        "limitations": list(PORTFOLIO_LIMITATIONS),
        "pagetrace_version": __version__,
        "processor_versions": {
            "ocr_engine": ocr.processor.engine_version,
            "ocr_inference_backend": ocr.processor.inference_backend_version,
            "pdf_layout_backend": structured.processor.pdf_layout_backend_version,
            "pdf_renderer": ocr.processor.pdf_renderer_version,
            "text_pdf_backend": text.extractor.pdf_backend_version,
        },
        "schema_version": PORTFOLIO_SCHEMA_VERSION,
        "type": "pagetrace_portfolio",
    }
    (staging / PORTFOLIO_MANIFEST_NAME).write_bytes(_canonical_json(summary))
    return PortfolioDemoResult(
        output_directory=staging,
        manifest_path=staging / PORTFOLIO_MANIFEST_NAME,
        document_id=document.document_id,
        corpus_artifact_id=corpus.artifact_id,
        answer_id=answer.answer_id,
        abstention_id=abstention.answer_id,
        quality_report_id=report.report_id,
    )


def _qa_summary(result: QaResult) -> dict[str, object]:
    hits = {hit.rank: hit for hit in result.retrieval.hits}
    return {
        "abstention_reason": (
            result.abstention_reason.value if result.abstention_reason is not None else None
        ),
        "answer": result.answer,
        "answer_id": result.answer_id,
        "citations": [
            {
                "chunk_id": citation.chunk_id,
                "excerpt": citation.excerpt,
                "excerpt_end": citation.excerpt_end,
                "excerpt_start": citation.excerpt_start,
                "matched_terms": list(citation.matched_terms),
                "page_number": hits[citation.retrieval_rank].page_number,
                "query_term_coverage": citation.query_term_coverage,
                "retrieval_rank": citation.retrieval_rank,
            }
            for citation in result.citations
        ],
        "question": result.retrieval.query,
        "status": result.status.value,
    }


def _new_output_target(output_directory: Path) -> Path:
    if not isinstance(output_directory, Path):
        raise TypeError("output_directory must be a pathlib.Path")
    target = output_directory.expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise PortfolioDemoError("portfolio output directory must not already exist")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PortfolioDemoError("portfolio output parent could not be prepared") from exc
    return target


def _portfolio_pdf_bytes(page_texts: tuple[str, ...]) -> bytes:
    if not page_texts:
        raise ValueError("portfolio PDF requires at least one page")
    font_object_id = 3 + 2 * len(page_texts)
    page_ids = tuple(3 + 2 * index for index in range(len(page_texts)))
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] "
            f"/Count {len(page_ids)} >>"
        ).encode("ascii"),
        font_object_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, text in zip(page_ids, page_texts, strict=True):
        try:
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content = f"BT\n/F1 12 Tf\n72 720 Td\n({escaped}) Tj\nET\n".encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("portfolio PDF fixture text must be ASCII") from exc
        stream_id = page_id + 1
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_object_id} 0 R >> >> "
            f"/Contents {stream_id} 0 R >>"
        ).encode("ascii")
        objects[stream_id] = (
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"endstream"
        )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (font_object_id + 1)
    for object_id in range(1, font_object_id + 1):
        offsets[object_id] = len(output)
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {font_object_id + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {font_object_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
