# Milestone Acceptance Record

This record accepts the PageTrace v1.0 implementation within the explicit boundaries documented
in the roadmap, security policy, portfolio guide, and operational runbooks. Acceptance confirms
that the planned capability exists, is tested, and is reproducible. It does not convert documented
limitations into supported features or make unmeasured accuracy, security, or deployment claims.

## Decision

- Acceptance date: 2026-09-19
- Reviewed baseline: `30d150341e0f10245791ae9e626c6ccf9d10b3e5`
- Scope: Milestones 2B through 11; Milestones 0, 1, and 2A were already complete
- Decision: accepted for the PageTrace v1.0 portfolio release candidate
- Release state: the `v1.0.0` candidate tag was blocked by frontend dependency audit findings;
  no release was published, and the corrected `v1.0.1` candidate has passed local validation and
  is pending its immutable tagged workflow

## Accepted evidence

| Milestone | Implementation evidence | Acceptance boundary |
| --- | --- | --- |
| 2B — OCR Engine & Evaluation | `7d4e4ac`, plus focused mock-scope correction `b4fb886`; `src/pagetrace/ocr/`; OCR engine, evaluation, integration, model, rendering, and storage tests | RapidOCR/ONNX CPU baseline with measured fixtures; OCR output remains untrusted derived data |
| 3 — Structured Document Representation | `e8e9987`; `src/pagetrace/structure/`; structure, layout, model, and storage tests | Positioned text and deterministic line-based PDF tables, not general layout understanding |
| 4 — Provenance-aware Chunking & Corpus Model | `22c849f`; `src/pagetrace/corpus/`; corpus model and storage tests | Page-bounded deterministic chunks; tables remain linked through structure provenance |
| 5 — Retrieval Baselines & Evaluation | `1bd5605`; `src/pagetrace/retrieval/`; retrieval and retrieval-model tests | Transparent lexical BM25 baseline, not persistent or vector retrieval |
| 6 — Evidence-grounded QA | `3d0183d`; `src/pagetrace/qa/`; QA tests | Extractive exact-source answers and explicit abstention, not abstractive synthesis |
| 7 — Evaluation & Quality System | `dbdb982`; `src/pagetrace/quality/`; quality tests | Results apply to supplied fixtures, judgments, gates, and baselines only |
| 8 — Product Backend | `881a7af`; `src/pagetrace/backend/`; backend CLI, HTTP, store, and workflow tests | Authenticated loopback single-host boundary, not a remote multi-user deployment |
| 9 — Evidence-first Web Product | `b0b40e2`; `web/` and packaged web assets; frontend lint, tests, and production build | Single-operator inspection interface with memory-only browser authentication |
| 10 — Production & Security Hardening | `96e66ee`; CI/Dependabot controls, deployment and incident runbooks, adversarial boundary tests | No hard parser CPU/memory sandbox, TLS termination, remote access, or multi-user authorization |
| 11 — Portfolio v1.0 | `30d1503`; `src/pagetrace/portfolio.py`; portfolio, CLI, package, and clean-wheel tests | Deterministic synthetic evidence demonstration, not a representative accuracy benchmark |

## Validation reviewed

The accepted feature baseline and corrective 1.0.1 candidate completed the following
release-candidate checks:

- Ruff lint and formatting checks across all 101 Python source and test files;
- strict mypy validation for Python 3.12 across all 101 Python source and test files;
- 567 passing Python tests, 3 skipped integration cases, and 90.86% branch-aware coverage;
- npm dependency audit with no reported vulnerabilities after upgrading to Vite 8.3.0 and Vitest
  5.0.1, ESLint, 4 passing frontend tests, and a successful production build;
- an isolated Python dependency audit with no known third-party vulnerabilities;
- successful `pagetrace-1.0.1` wheel and source-archive builds with strict Twine validation; and
- two clean-wheel portfolio executions with the same canonical manifest SHA-256
  `4ca29cb12b176b3da83c3d7732d1bc6f787c0b66897f23cb0b5dabebe777271f`, an exact page-one
  citation, explicit no-hit abstention, and passing quality gates.

## Retained limitations

Acceptance does not waive the limitations in [`PORTFOLIO.md`](PORTFOLIO.md),
[`../SECURITY.md`](../SECURITY.md), [`DEPLOYMENT.md`](DEPLOYMENT.md), or
[`INCIDENT_RESPONSE.md`](INCIDENT_RESPONSE.md). In particular, PageTrace v1.0 remains a local,
single-operator portfolio system. A version tag, release-workflow result, artifact review, and
publication decision remain separate release steps.
