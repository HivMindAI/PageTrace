from __future__ import annotations

import threading
from pathlib import Path
from typing import cast

import pytest

import pagetrace.backend.cli
from pagetrace.backend import BackendService, SqliteJobStore, WorkflowName
from pagetrace.backend.cli import build_parser, main


def _base(tmp_path: Path) -> list[str]:
    inputs = tmp_path / "inputs"
    inputs.mkdir(exist_ok=True)
    return [
        "--database",
        str(tmp_path / "backend.sqlite3"),
        "--store",
        str(tmp_path / "artifacts"),
        "--input-root",
        str(inputs),
    ]


def test_backend_cli_init_and_idle_worker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = _base(tmp_path)
    assert main([*arguments, "init"]) == 0
    assert capsys.readouterr().out == "PageTrace backend database is ready\n"

    assert main([*arguments, "worker", "--once"]) == 0
    assert capsys.readouterr().err == ""


def test_backend_cli_expected_errors_have_no_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _base(tmp_path)
    monkeypatch.delenv("PAGETRACE_BACKEND_TOKEN", raising=False)
    assert main([*arguments, "serve"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "bearer token environment variable is not set" in captured.err
    assert "Traceback" not in captured.err

    invalid_root = tmp_path / "file"
    invalid_root.write_text("not a directory", encoding="utf-8")
    bad = [*arguments]
    bad[bad.index(str(tmp_path / "inputs"))] = str(invalid_root)
    assert main([*bad, "init"]) == 2
    assert "non-symlink directory" in capsys.readouterr().err


def test_backend_cli_parser_validation() -> None:
    with pytest.raises(SystemExit, match="2"):
        build_parser().parse_args([])
    with pytest.raises(SystemExit, match="2"):
        build_parser().parse_args(["worker", "--poll-interval", "0"])
    with pytest.raises(SystemExit, match="2"):
        build_parser().parse_args(["serve", "--port", "70000"])
    invalid = (
        ["--max-retained-jobs", "0", "init"],
        ["purge", "--limit", "0", "--older-than-hours", "1"],
        ["purge", "--older-than-hours", "nan"],
        ["purge", "--finished-before", "2026-01-01"],
        ["serve", "--connection-timeout", "0"],
    )
    for arguments in invalid:
        with pytest.raises(SystemExit, match="2"):
            build_parser().parse_args(arguments)


def test_backend_cli_purge_preview_and_confirmation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = _base(tmp_path)
    assert main([*arguments, "init"]) == 0
    capsys.readouterr()

    service = pagetrace.backend.cli._service(build_parser().parse_args([*arguments, "init"]))
    service.initialize()
    job, _ = service.store.submit(
        WorkflowName.EVALUATE_QUALITY,
        {},
        idempotency_key="purge-me",
    )
    service.store.request_cancel(job.job_id)

    cutoff = "2999-01-01T00:00:00Z"
    assert main([*arguments, "purge", "--finished-before", cutoff]) == 0
    assert "Purge preview: 1 terminal job(s)" in capsys.readouterr().out
    assert service.store.get(job.job_id).status.value == "cancelled"

    assert main([*arguments, "purge", "--finished-before", cutoff, "--confirm"]) == 0
    assert "Purged 1 terminal job(s)" in capsys.readouterr().out

    assert main([*arguments, "purge", "--older-than-hours", "1"]) == 0
    assert "Purge preview: 0 terminal job(s)" in capsys.readouterr().out


def test_backend_cli_purge_does_not_prepare_workflow_roots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "standalone.sqlite3"
    SqliteJobStore(database).initialize()
    artifact_store = tmp_path / "must-not-be-created"
    missing_input = tmp_path / "missing-input"

    assert (
        main(
            [
                "--database",
                str(database),
                "--store",
                str(artifact_store),
                "--input-root",
                str(missing_input),
                "purge",
                "--older-than-hours",
                "1",
            ]
        )
        == 0
    )
    assert "Purge preview: 0 terminal job(s)" in capsys.readouterr().out
    assert not artifact_store.exists()


def test_backend_cli_serve_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    class FakeServer:
        server_port = 4321

        def serve_forever(self, *, poll_interval: float) -> None:
            calls.append(f"serve:{poll_interval}")

        def server_close(self) -> None:
            calls.append("close")

    class FakeWorker:
        def __init__(self, service: object, *, poll_interval_seconds: float) -> None:
            calls.append(f"worker:{poll_interval_seconds}")

        def start(self) -> None:
            calls.append("start")

        def stop(self, *, timeout_seconds: float) -> bool:
            calls.append(f"stop:{timeout_seconds}")
            return True

    def fake_server(*args: object, **kwargs: object) -> FakeServer:
        calls.append("server")
        return FakeServer()

    monkeypatch.setenv("TEST_BACKEND_TOKEN", "x" * 32)
    monkeypatch.setattr(pagetrace.backend.cli, "create_http_server", fake_server)
    monkeypatch.setattr(pagetrace.backend.cli, "BackgroundWorker", FakeWorker)

    arguments = _base(tmp_path)
    assert (
        main(
            [
                *arguments,
                "serve",
                "--token-env",
                "TEST_BACKEND_TOKEN",
                "--poll-interval",
                "0.5",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "PageTrace web app listening on http://127.0.0.1:4321\n"
    assert calls == ["server", "worker:0.5", "start", "serve:0.25", "close", "stop:30.0"]


def test_backend_cli_continuous_worker_stops_on_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeWorker:
        def __init__(self, service: object, *, poll_interval_seconds: float) -> None:
            calls.append(f"worker:{poll_interval_seconds}")

        def start(self) -> None:
            calls.append("start")

        def stop(self, *, timeout_seconds: float) -> bool:
            calls.append(f"stop:{timeout_seconds}")
            return True

    class FakeEvent:
        def wait(self, timeout: float) -> bool:
            raise KeyboardInterrupt

    monkeypatch.setattr(pagetrace.backend.cli, "BackgroundWorker", FakeWorker)
    monkeypatch.setattr(threading, "Event", FakeEvent)
    service = cast(BackendService, object())
    assert pagetrace.backend.cli._run_worker(service, once=False, poll_interval=0.75) == 0
    assert calls == ["worker:0.75", "start", "stop:30.0"]


def test_backend_cli_worker_and_server_stop_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailedWorker:
        def __init__(self, service: object, *, poll_interval_seconds: float) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self, *, timeout_seconds: float) -> bool:
            return False

    class InterruptEvent:
        def wait(self, timeout: float) -> bool:
            raise KeyboardInterrupt

    monkeypatch.setattr(pagetrace.backend.cli, "BackgroundWorker", FailedWorker)
    monkeypatch.setattr(threading, "Event", InterruptEvent)
    service = cast(BackendService, object())
    assert pagetrace.backend.cli._run_worker(service, once=False, poll_interval=1) == 1
    assert "did not stop cleanly" in capsys.readouterr().err
