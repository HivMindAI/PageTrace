# Release Process

PageTrace releases are built from an exact semantic-version tag after the corresponding commit is
reviewed on `main`. The repository does not automatically publish to PyPI or create a GitHub
release; the tag workflow produces a reviewable, checksummed artifact bundle first.

## Prepare a release

1. Synchronize the version in `pyproject.toml`, `src/pagetrace/__init__.py`, `web/package.json`, and
   `web/package-lock.json`.
2. Move completed changelog entries under the dated version heading and leave `Unreleased` ready
   for later work.
3. Confirm [`ACCEPTANCE.md`](ACCEPTANCE.md) covers every milestone included in the release and does
   not waive any documented limitation.
4. Review direct dependency constraints and release notes. Update
   `requirements/portfolio-constraints.txt` only after reproducing and reviewing changed evidence.
5. Run the complete local validation matrix:

```bash
ruff check .
ruff format --check .
mypy --python-version 3.12 src tests
pytest
npm --prefix web audit --audit-level=high
npm --prefix web run lint
npm --prefix web test
npm --prefix web run build
git diff --exit-code -- src/pagetrace/web/dist
pagetrace portfolio-demo portfolio-run-one
pagetrace portfolio-demo portfolio-run-two
python -m build
python -m twine check --strict dist/*
git diff --check
```

6. Compare the two portfolio manifests byte for byte, inspect their exact citations and limitations,
   and remove the local output directories after review.
7. Confirm the commit is on `main`, CI is green, and the working tree is clean.

## Build the tagged candidate

Create and push an exact version tag, preferably signed:

```bash
git tag -s v1.0.0 -m "PageTrace v1.0.0"
git push origin v1.0.0
```

The `Release Candidate` workflow rejects a tag that does not equal `v` plus the package version.
It audits dependencies, verifies the frontend and Python project, runs the complete test suite,
reproduces the portfolio manifest twice, builds wheel/source distributions, writes SHA-256
checksums, and uploads a 30-day candidate artifact using an immutable action revision.

## Review and publish

- Download the workflow artifact and verify `SHA256SUMS` before installation.
- Install the wheel in a clean environment and rerun `pagetrace portfolio-demo`.
- Confirm the release notes and portfolio limitations still match observed behavior.
- Only then attach the reviewed files to a GitHub release or publish them to a package index using
  a separately authorized, trusted-publishing process.

Never reuse or move an existing exact release tag. A correction after publication receives a new
patch version and a new changelog entry.
