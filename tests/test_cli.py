from __future__ import annotations

import json
from pathlib import Path

import pytest

import pagetrace.cli
from pagetrace.cli import build_parser, main
from pagetrace.documents import ingest_document
from pagetrace.extraction import ExtractionLimitError, extract_document_text
from pagetrace.ocr import OcrEvaluationError
from pagetrace.structure import StructureProcessingError
from tests.conftest import ImageFactory
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
