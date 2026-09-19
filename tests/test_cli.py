from __future__ import annotations

import json
from pathlib import Path

import pytest

import pagetrace.cli
from pagetrace.cli import build_parser, main
from pagetrace.corpus import CorpusLimitError, build_corpus_artifact
from pagetrace.documents import ingest_document
from pagetrace.extraction import ExtractionLimitError, extract_document_text
from pagetrace.ocr import OcrEvaluationError
from pagetrace.portfolio import PortfolioDemoError, PortfolioDemoResult
from pagetrace.qa import QaConfig, QaError, answer_from_retrieval
from pagetrace.quality import (
    MetricComparator,
    MetricGate,
    QualityMetricName,
    QualityPolicy,
    RegressionRule,
    TextQualityCase,
    create_quality_suite,
    evaluate_quality,
    serialize_quality_report,
    serialize_quality_suite,
)
from pagetrace.retrieval import (
    RetrievalConfig,
    RetrievalEvaluationError,
    RetrievalJudgment,
    RetrievalQueryError,
    create_retrieval_dataset,
    rank_corpus,
    serialize_retrieval_dataset,
)
from pagetrace.structure import StructureProcessingError
from tests.conftest import ImageFactory
from tests.test_corpus_models import _source as corpus_source
from tests.test_quality import _full_suite as full_quality_suite
from tests.test_structure_models import _artifact as structured_artifact


def test_cli_ingest_and_inspect_plain_output(
    tmp_path: Path,
    image_factory: ImageFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = image_factory(tmp_path / "image.png", image_format="PNG")
    store = tmp_path / "store"

    assert main(["ingest", str(source), "--store", str(store)]) == 0
    ingestion_output = capsys.readouterr().out
    document_id = ingestion_output.splitlines()[0].split(": ", 1)[1]
    assert "SHA-256:" in ingestion_output
    assert "media type: image/png" in ingestion_output
    assert "page count: 1" in ingestion_output

    assert main(["inspect", document_id, "--store", str(store)]) == 0
    assert f"document id: {document_id}" in capsys.readouterr().out


def test_cli_json_output_is_machine_readable(
    tmp_path: Path,
    image_factory: ImageFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = image_factory(tmp_path / "image.jpg", image_format="JPEG")

    assert main(["ingest", str(source), "--store", str(tmp_path / "store"), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["media_type"] == "image/jpeg"
    assert payload["page_count"] == 1


def test_cli_expected_error_has_no_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "unsupported.txt"
    source.write_text("unsupported", encoding="utf-8")

    assert main(["ingest", str(source), "--store", str(tmp_path / "store")]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("pagetrace: error:")
    assert "Traceback" not in captured.err


def test_cli_parser_requires_a_command() -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args([])
    assert error.value.code == 2


def test_cli_portfolio_demo_output_and_expected_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "portfolio"
    result = PortfolioDemoResult(
        output_directory=output,
        manifest_path=output / "portfolio-manifest.json",
        document_id=f"sha256-{'1' * 64}",
        corpus_artifact_id=f"corpus-sha256-{'2' * 64}",
        answer_id=f"answer-sha256-{'3' * 64}",
        abstention_id=f"answer-sha256-{'4' * 64}",
        quality_report_id=f"quality-report-sha256-{'5' * 64}",
    )
    monkeypatch.setattr(pagetrace.cli, "run_portfolio_demo", lambda _output: result)

    assert main(["portfolio-demo", str(output)]) == 0
    rendered = capsys.readouterr().out
    assert f"portfolio manifest: {result.manifest_path}" in rendered
    assert f"document id: {result.document_id}" in rendered
    assert f"quality report id: {result.quality_report_id}" in rendered

    def fail(_output: Path) -> PortfolioDemoResult:
        raise PortfolioDemoError("output already exists")

    monkeypatch.setattr(pagetrace.cli, "run_portfolio_demo", fail)
    assert main(["portfolio-demo", str(output)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pagetrace: error: output already exists\n"


def test_cli_extract_and_inspect_text_plain_output(
    tmp_path: Path,
    image_factory: ImageFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        image_factory(tmp_path / "image.png", image_format="PNG"), store=store
    )

    assert main(["extract-text", manifest.document_id, "--store", str(store)]) == 0
    extraction_output = capsys.readouterr().out
    artifact_id = extraction_output.splitlines()[0].split(": ", 1)[1]
    assert f"document id: {manifest.document_id}" in extraction_output
    assert "page 1: ocr_candidate (0 non-whitespace characters)" in extraction_output

    assert (
        main(
            [
                "inspect-text",
                manifest.document_id,
                artifact_id,
                "--store",
                str(store),
            ]
        )
        == 0
    )
    assert f"text artifact id: {artifact_id}" in capsys.readouterr().out


def test_cli_text_json_output_separates_status_and_absent_text(
    tmp_path: Path,
    image_factory: ImageFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = tmp_path / "store"
    manifest = ingest_document(
        image_factory(tmp_path / "image.jpg", image_format="JPEG"), store=store
    )

    assert main(["extract-text", manifest.document_id, "--store", str(store), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["pages"][0]["status"] == "ocr_candidate"
    assert payload["pages"][0]["text"] is None
    assert "OCR required" not in json.dumps(payload)


def test_cli_text_domain_failure_has_no_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_id = f"sha256-{'0' * 64}"

    assert main(["extract-text", missing_id, "--store", str(tmp_path / "store")]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("pagetrace: error:")
    assert "Traceback" not in captured.err


def test_cli_does_not_swallow_unexpected_extraction_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_unexpectedly(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("programmer failure")

    monkeypatch.setattr(pagetrace.cli, "extract_document_text", fail_unexpectedly)
    with pytest.raises(RuntimeError, match="programmer failure"):
        main(["extract-text", f"sha256-{'0' * 64}"])


def test_cli_extraction_limit_failure_is_concise(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def exceed_limit(*_args: object, **_kwargs: object) -> None:
        raise ExtractionLimitError("test output exceeds configured extraction limit")

    monkeypatch.setattr(pagetrace.cli, "extract_document_text", exceed_limit)

    assert main(["extract-text", f"sha256-{'0' * 64}"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ("pagetrace: error: test output exceeds configured extraction limit\n")
    assert "Traceback" not in captured.err


def test_cli_ocr_and_inspection_plain_output(
    tmp_path: Path,
    image_factory: ImageFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = tmp_path / "store"
    source = image_factory(tmp_path / "image.png", image_format="PNG", size=(40, 30))
    manifest = ingest_document(source, store=store)
    text_artifact = extract_document_text(manifest.document_id, store=store)

    assert (
        main(
            [
                "ocr",
                manifest.document_id,
                text_artifact.artifact_id,
                "--candidates-only",
                "--store",
                str(store),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    artifact_id = output.splitlines()[0].split(": ", 1)[1]
    assert "OCR engine: rapidocr" in output
    assert "selected pages: 1/1" in output

    assert (
        main(
            [
                "inspect-ocr",
                manifest.document_id,
                artifact_id,
                "--store",
                str(store),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact_id"] == artifact_id
    assert payload["configuration"]["routing_policy"] == "ocr_candidates_only"


def test_cli_evaluates_utf8_text_in_plain_and_json_forms(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reference = tmp_path / "reference.txt"
    prediction = tmp_path / "prediction.txt"
    reference.write_text("one two", encoding="utf-8")
    prediction.write_text("one too", encoding="utf-8")

    assert main(["evaluate-ocr", str(reference), str(prediction)]) == 0
    output = capsys.readouterr().out
    assert "exact match: no" in output
    assert "character error rate:" in output
    assert "word error rate:" in output

    assert main(["evaluate-ocr", str(reference), str(reference), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["exact_match"] is True


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("invalid.txt", b"\xff", "valid UTF-8"),
        ("missing.txt", None, "could not be read"),
    ],
)
def test_cli_evaluation_input_failures_are_concise(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
    data: bytes | None,
    message: str,
) -> None:
    reference = tmp_path / "reference.txt"
    reference.write_text("reference", encoding="utf-8")
    prediction = tmp_path / name
    if data is not None:
        prediction.write_bytes(data)

    assert main(["evaluate-ocr", str(reference), str(prediction)]) == 2
    assert message in capsys.readouterr().err


def test_cli_evaluation_rejects_non_regular_input(tmp_path: Path) -> None:
    with pytest.raises(OcrEvaluationError, match="regular"):
        pagetrace.cli._read_evaluation_text(tmp_path)


def test_cli_structure_and_inspection_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = structured_artifact()
    monkeypatch.setattr(
        pagetrace.cli,
        "structure_document",
        lambda *_args, **_kwargs: artifact,
    )

    assert (
        main(
            [
                "structure",
                artifact.document_id,
                artifact.source_text_artifact_id,
                artifact.source_ocr_artifact_id,
                "--store",
                str(tmp_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert f"structured artifact id: {artifact.artifact_id}" in output
    assert "positioned text spans: 1" in output
    assert "tables: 1" in output

    monkeypatch.setattr(
        pagetrace.cli,
        "load_structured_document",
        lambda *_args, **_kwargs: artifact,
    )
    assert (
        main(
            [
                "inspect-structure",
                artifact.document_id,
                artifact.artifact_id,
                "--store",
                str(tmp_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact_id"] == artifact.artifact_id
    assert payload["pages"][0]["coordinate_origin"] == "top_left"


def test_cli_structure_failure_is_concise(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise StructureProcessingError("structure failed safely")

    monkeypatch.setattr(pagetrace.cli, "structure_document", fail)

    assert (
        main(
            [
                "structure",
                f"sha256-{'1' * 64}",
                f"text-sha256-{'2' * 64}",
                f"ocr-sha256-{'3' * 64}",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pagetrace: error: structure failed safely\n"


def test_cli_build_and_inspect_corpus_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = build_corpus_artifact(corpus_source((("PageTrace", "corpus"),)))
    monkeypatch.setattr(pagetrace.cli, "build_corpus", lambda *_args, **_kwargs: artifact)

    assert (
        main(
            [
                "build-corpus",
                artifact.document_id,
                artifact.source_structure_artifact_id,
                "--store",
                str(tmp_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert f"corpus artifact id: {artifact.artifact_id}" in output
    assert "source text spans: 2" in output
    assert "chunks: 1" in output

    monkeypatch.setattr(pagetrace.cli, "load_corpus_artifact", lambda *_args, **_kwargs: artifact)
    assert (
        main(
            [
                "inspect-corpus",
                artifact.document_id,
                artifact.artifact_id,
                "--store",
                str(tmp_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact_id"] == artifact.artifact_id
    assert payload["chunks"][0]["fragments"][0]["span_id"]


def test_cli_corpus_failure_is_concise(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise CorpusLimitError("corpus limit reached")

    monkeypatch.setattr(pagetrace.cli, "build_corpus", fail)
    assert (
        main(
            [
                "build-corpus",
                f"sha256-{'1' * 64}",
                f"structure-sha256-{'2' * 64}",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pagetrace: error: corpus limit reached\n"


def test_cli_retrieve_plain_and_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = build_corpus_artifact(corpus_source((("alpha beta",), ("beta gamma",))))
    result = rank_corpus(corpus, "beta", configuration=RetrievalConfig(top_k=1))
    monkeypatch.setattr(pagetrace.cli, "retrieve", lambda *_args, **_kwargs: result)

    arguments = [
        "retrieve",
        corpus.document_id,
        corpus.artifact_id,
        "beta",
        "--top-k",
        "1",
        "--store",
        str(tmp_path),
    ]
    assert main(arguments) == 0
    output = capsys.readouterr().out
    assert f"retrieval result id: {result.result_id}" in output
    assert "hits: 1/2" in output
    assert "rank 1:" in output

    assert main([*arguments, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result_id"] == result.result_id
    assert payload["hits"][0]["chunk_id"] == corpus.chunks[0].chunk_id


def test_cli_evaluate_retrieval_from_canonical_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = build_corpus_artifact(corpus_source((("alpha beta",), ("beta gamma",))))
    dataset = create_retrieval_dataset(
        corpus.artifact_id,
        (RetrievalJudgment("q1", "alpha", (corpus.chunks[0].chunk_id,)),),
    )
    dataset_path = tmp_path / "retrieval-dataset.json"
    dataset_path.write_bytes(serialize_retrieval_dataset(dataset))
    monkeypatch.setattr(pagetrace.cli, "load_corpus_artifact", lambda *_args, **_kwargs: corpus)

    assert (
        main(
            [
                "evaluate-retrieval",
                corpus.document_id,
                corpus.artifact_id,
                str(dataset_path),
                "--top-k",
                "2",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset_id"] == dataset.dataset_id
    assert payload["mean_recall"] == 1.0
    assert payload["mean_precision"] == 0.5


def test_cli_retrieval_failures_are_concise(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise RetrievalQueryError("query has no terms")

    monkeypatch.setattr(pagetrace.cli, "retrieve", fail)
    assert (
        main(
            [
                "retrieve",
                f"sha256-{'1' * 64}",
                f"corpus-sha256-{'2' * 64}",
                "!!!",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pagetrace: error: query has no terms\n"


@pytest.mark.parametrize("value", ["0", "1001", "not-an-integer"])
def test_cli_retrieval_cutoff_is_bounded(value: str) -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(
            [
                "retrieve",
                f"sha256-{'1' * 64}",
                f"corpus-sha256-{'2' * 64}",
                "query",
                "--top-k",
                value,
            ]
        )
    assert error.value.code == 2


def test_cli_retrieval_dataset_rejects_non_regular_input(tmp_path: Path) -> None:
    with pytest.raises(RetrievalEvaluationError, match="regular"):
        pagetrace.cli._read_retrieval_dataset(tmp_path)


def test_cli_answer_plain_and_json_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = build_corpus_artifact(corpus_source((("alpha answer.",),)))
    result = answer_from_retrieval(
        rank_corpus(corpus, "alpha", configuration=RetrievalConfig(top_k=1)),
        configuration=QaConfig(max_evidence_items=1),
    )
    monkeypatch.setattr(pagetrace.cli, "answer_question", lambda *_args, **_kwargs: result)
    arguments = [
        "answer",
        corpus.document_id,
        corpus.artifact_id,
        "alpha",
        "--top-k",
        "1",
        "--max-evidence",
        "1",
        "--store",
        str(tmp_path),
    ]

    assert main(arguments) == 0
    output = capsys.readouterr().out
    assert f"answer id: {result.answer_id}" in output
    assert "status: answered" in output
    assert "[1] page 1, chunk 1" in output

    assert main([*arguments, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["answer"] == "alpha answer."
    assert payload["citations"][0]["chunk_id"] == corpus.chunks[0].chunk_id


def test_cli_answer_abstention_and_error_are_explicit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = build_corpus_artifact(corpus_source((("alpha",),)))
    abstained = answer_from_retrieval(rank_corpus(corpus, "missing"))
    monkeypatch.setattr(pagetrace.cli, "answer_question", lambda *_args, **_kwargs: abstained)
    arguments = ["answer", corpus.document_id, corpus.artifact_id, "missing"]

    assert main(arguments) == 0
    assert "abstention reason: no_retrieval_hits" in capsys.readouterr().out

    def fail(*_args: object, **_kwargs: object) -> None:
        raise QaError("answer failed safely")

    monkeypatch.setattr(pagetrace.cli, "answer_question", fail)
    assert main(arguments) == 2
    assert capsys.readouterr().err == "pagetrace: error: answer failed safely\n"


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--max-evidence", "0"),
        ("--max-evidence", "101"),
        ("--max-answer-characters", "0"),
        ("--max-answer-characters", "100001"),
        ("--minimum-coverage", "0"),
        ("--minimum-coverage", "1.1"),
        ("--minimum-coverage", "not-a-number"),
    ],
)
def test_cli_answer_bounds_are_enforced(option: str, value: str) -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(
            [
                "answer",
                f"sha256-{'1' * 64}",
                f"corpus-sha256-{'2' * 64}",
                "question",
                option,
                value,
            ]
        )
    assert error.value.code == 2


def test_cli_evaluate_quality_plain_and_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    suite = full_quality_suite()
    suite_path = tmp_path / "quality-suite.json"
    suite_path.write_bytes(serialize_quality_suite(suite))

    assert main(["evaluate-quality", str(suite_path)]) == 0
    output = capsys.readouterr().out
    assert f"suite id: {suite.suite_id}" in output
    assert "status: passed" in output
    assert "text.exact_match_rate:" in output
    assert "findings:" in output

    assert main(["evaluate-quality", str(suite_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["suite_id"] == suite.suite_id
    assert payload["status"] == "passed"


def test_cli_quality_gate_and_regression_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_suite = create_quality_suite(text_cases=(TextQualityCase("baseline", True, 0.0, 0.0),))
    baseline_report = evaluate_quality(baseline_suite)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_bytes(serialize_quality_report(baseline_report))

    failed_suite = create_quality_suite(
        text_cases=(TextQualityCase("current", False, 1.0, 1.0),),
        policy=QualityPolicy(
            policy_id="failed",
            gates=(
                MetricGate(
                    QualityMetricName.TEXT_EXACT_MATCH_RATE,
                    MetricComparator.AT_LEAST,
                    1.0,
                ),
            ),
            regression_rules=(RegressionRule(QualityMetricName.TEXT_EXACT_MATCH_RATE),),
        ),
    )
    failed_path = tmp_path / "failed-suite.json"
    failed_path.write_bytes(serialize_quality_suite(failed_suite))

    assert (
        main(
            [
                "evaluate-quality",
                str(failed_path),
                "--baseline",
                str(baseline_path),
            ]
        )
        == 1
    )
    assert "status: failed" in capsys.readouterr().out

    incomplete_suite = create_quality_suite(
        text_cases=(TextQualityCase("text", True, 0.0, 0.0),),
        policy=QualityPolicy(
            policy_id="incomplete",
            gates=(
                MetricGate(
                    QualityMetricName.HUMAN_CORRECTNESS,
                    MetricComparator.AT_LEAST,
                    4.0,
                ),
            ),
        ),
    )
    incomplete_path = tmp_path / "incomplete-suite.json"
    incomplete_path.write_bytes(serialize_quality_suite(incomplete_suite))
    assert main(["evaluate-quality", str(incomplete_path)]) == 3
    assert "status: incomplete" in capsys.readouterr().out


def test_cli_quality_input_failure_is_concise(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["evaluate-quality", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "regular non-symlink" in captured.err
