from __future__ import annotations

import json
from pathlib import Path

import pytest

from pagetrace.cli import build_parser, main
from tests.conftest import ImageFactory


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
