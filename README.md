# PageTrace

> Understand documents. Trace every answer to its source.

**PageTrace — Multimodal Document Intelligence Platform** is an early-stage project exploring
how document understanding systems can make evidence, provenance, and evaluation first-class
concerns.

## Vision

PageTrace is intended to help people understand complex documents while preserving a clear path
from every derived result back to its supporting source. The project is guided by four ideas:

- **Traceability:** outputs should retain precise, inspectable links to source evidence.
- **Provenance:** transformations should record where information came from and how it changed.
- **Evaluation:** measurable quality should shape development from the first real capability.
- **Untrusted-document security:** uploaded content should be treated as hostile data, never as
  executable instructions.

## Current status

PageTrace is **pre-alpha**. Milestone 0 contains repository and Python package foundation only.
It does not ingest, parse, analyze, retrieve from, or answer questions about documents.

The runtime package is intentionally minimal while quality gates, packaging, documentation, and
continuous integration are established for future work.

## Planned conceptual pipeline

The following is a direction for later milestones, not current functionality:

```text
untrusted documents
        ↓
secure deterministic ingestion (planned)
        ↓
text and structure extraction (planned)
        ↓
provenance-aware corpus construction (planned)
        ↓
retrieval and evidence evaluation (planned)
        ↓
evidence-grounded answers and product experiences (planned)
```

See [ROADMAP.md](ROADMAP.md) for the staged plan and its scope boundaries.

## Development setup

PageTrace requires Python 3.11 or later.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

After installation, verify the package import:

```bash
python -c "import pagetrace; print(pagetrace.__name__)"
```

## Quality and validation

```bash
ruff check .
ruff format --check .
mypy src tests
pytest
python -m build
python -m twine check --strict dist/*
git diff --check
```

`pytest` enforces branch-aware coverage with a 90% minimum. The contribution guide documents the
clean-wheel installation smoke test used by continuous integration.

## Project policies

- [CONTRIBUTING.md](CONTRIBUTING.md) — local workflow and quality expectations
- [SECURITY.md](SECURITY.md) — security philosophy and vulnerability reporting
- [ROADMAP.md](ROADMAP.md) — milestone responsibilities
- [CHANGELOG.md](CHANGELOG.md) — unreleased changes

## License

PageTrace is available under the [MIT License](LICENSE).

