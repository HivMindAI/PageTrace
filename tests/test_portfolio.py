from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from pagetrace.portfolio import (
    PORTFOLIO_ABSTENTION_QUESTION,
    PORTFOLIO_ANSWER_QUESTION,
    PORTFOLIO_MANIFEST_NAME,
    PORTFOLIO_PAGE_TEXTS,
    PortfolioDemoError,
    run_portfolio_demo,
)
from pagetrace.qa import QaStatus, deserialize_qa_result
from pagetrace.quality import QualityReportStatus, deserialize_quality_report
from pagetrace.retrieval import deserialize_retrieval_evaluation


def test_portfolio_demo_is_reproducible_evidence_grounded_and_evaluated(
    tmp_path: Path,
) -> None:
    first = run_portfolio_demo(tmp_path / "first")
    second = run_portfolio_demo(tmp_path / "second")

    first_manifest = first.manifest_path.read_bytes()
    second_manifest = second.manifest_path.read_bytes()
    assert first_manifest == second_manifest

    payload = cast(dict[str, Any], json.loads(first_manifest))
    assert payload["schema_version"] == 1
    assert payload["type"] == "pagetrace_portfolio"
    assert payload["document"]["document_id"] == first.document_id
    assert payload["artifact_ids"]["corpus"] == first.corpus_artifact_id
    assert len(payload["limitations"]) >= 5

    supported = payload["demonstrations"]["supported_answer"]
    assert supported["question"] == PORTFOLIO_ANSWER_QUESTION
    assert supported["status"] == QaStatus.ANSWERED.value
    assert supported["answer"] == PORTFOLIO_PAGE_TEXTS[0]
    assert supported["citations"][0]["excerpt"] == supported["answer"]
    assert supported["citations"][0]["page_number"] == 1

    abstention = payload["demonstrations"]["abstention"]
    assert abstention["question"] == PORTFOLIO_ABSTENTION_QUESTION
    assert abstention["status"] == QaStatus.ABSTAINED.value
    assert abstention["answer"] is None
    assert abstention["citations"] == []
    assert abstention["abstention_reason"] == "no_retrieval_hits"

    retrieval = payload["evaluation"]["retrieval"]
    assert retrieval["case_count"] == 2
    assert retrieval["mean_recall"] == 1.0
    assert retrieval["mean_reciprocal_rank"] == 1.0
    quality = payload["evaluation"]["quality"]
    assert quality["status"] == QualityReportStatus.PASSED.value
    assert all(gate["status"] == "passed" for gate in quality["gates"])

    for name, expected_digest in cast(dict[str, str], payload["files"]).items():
        assert hashlib.sha256((first.output_directory / name).read_bytes()).hexdigest() == (
            expected_digest
        )

    answer = deserialize_qa_result(
        (first.output_directory / "qa-supported-answer.json").read_bytes()
    )
    assert answer.answer_id == first.answer_id
    assert answer.answer == PORTFOLIO_PAGE_TEXTS[0]
    abstained = deserialize_qa_result((first.output_directory / "qa-abstention.json").read_bytes())
    assert abstained.answer_id == first.abstention_id
    assert abstained.status is QaStatus.ABSTAINED
    evaluation = deserialize_retrieval_evaluation(
        (first.output_directory / "retrieval-evaluation.json").read_bytes()
    )
    assert evaluation.mean_recall == 1.0
    report = deserialize_quality_report(
        (first.output_directory / "quality-report.json").read_bytes()
    )
    assert report.report_id == first.quality_report_id
    assert report.status is QualityReportStatus.PASSED

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert first_manifest == canonical
    assert first.manifest_path.name == PORTFOLIO_MANIFEST_NAME


def test_portfolio_demo_requires_a_new_output_directory(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(PortfolioDemoError, match="must not already exist"):
        run_portfolio_demo(existing)
    with pytest.raises(TypeError, match=r"pathlib\.Path"):
        run_portfolio_demo("not-a-path")  # type: ignore[arg-type]


def test_portfolio_demo_reports_staging_creation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_to_create_staging(*_args: object, **_kwargs: object) -> str:
        raise OSError("simulated staging failure")

    monkeypatch.setattr("pagetrace.portfolio.tempfile.mkdtemp", fail_to_create_staging)

    with pytest.raises(PortfolioDemoError, match="staging directory could not be created"):
        run_portfolio_demo(tmp_path / "output")
