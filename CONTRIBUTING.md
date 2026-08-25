# Contributing to PageTrace

PageTrace is currently pre-alpha. Contributions should keep each milestone small, testable, and
truthful about what exists.

## Supported Python versions

Development supports Python 3.11 and 3.12. The package metadata allows Python 3.11 or later; new
language features must remain compatible with Python 3.11.

## Local setup

Create an isolated environment and install the project plus its development tools:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The editable installation is required so tests import the installed `src/` package rather than
depending on the repository root being importable.

## Required checks

Run these commands before requesting review:

```bash
ruff check .
ruff format --check .
mypy src tests
pytest
python -m build
python -m twine check --strict dist/*
git diff --check
```

Use `ruff format .` to apply formatting. Do not weaken lint, typing, test, or coverage gates merely
to make continuous integration pass; fix the underlying issue or document a narrowly justified
exception.

`pytest` includes branch coverage and fails below 90%. Behavior changes must include focused tests
that demonstrate the intended result and meaningful failure cases.

## Clean-wheel smoke test

After `python -m build`, create a fresh virtual environment, install the wheel from `dist/`, move
outside the source checkout, and run:

```bash
python -m pip install dist/*.whl
python -I -c "import pagetrace; print(pagetrace.__name__)"
pagetrace --help
python -I -m pagetrace --help
```

The smoke test must use the wheel's interpreter and must not rely on an editable installation,
`PYTHONPATH`, or the source checkout. Installing the wheel must resolve its declared pypdf and
Pillow runtime dependencies. The GitHub Actions workflow provides the canonical automated
implementation of this check.

## Document-ingestion changes

Document fixtures should be tiny and generated programmatically where practical. Tests involving
untrusted documents must exercise real parser/storage behavior and relevant failure cases rather
than mocking away the ingestion boundary. Preserve deterministic manifests: do not add source
paths, filenames, timestamps, machine identity, or other environment-derived values to the
canonical artifact.

Milestone 1 runtime dependencies are intentionally limited to pypdf (BSD-3-Clause) for PDF
structure inspection and Pillow (MIT-CMU) for PNG/JPEG validation and metadata. New runtime
dependencies require a documented capability need and license review.

## Git hygiene

- Keep changes scoped to one coherent concern.
- Review `git status` and `git diff` before sharing work.
- Do not commit virtual environments, caches, coverage data, build products, or secrets.
- Write clear commit messages and avoid unrelated formatting churn.
- Update documentation and the `[Unreleased]` changelog when behavior or contributor workflow
  changes.
- Do not bypass branch protections or publish packages from a development branch.
