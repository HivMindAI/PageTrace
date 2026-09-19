# PageTrace v1.0 Portfolio

PageTrace v1.0 is an evidence-first document-intelligence portfolio release. Its demonstration
processes a real deterministic PDF byte stream through ingestion, text extraction, OCR routing,
positioned structure, corpus construction, BM25 retrieval, extractive question answering, and
cross-stage quality evaluation. The source document is synthetic and intentionally small; it does
not represent general document accuracy.

## Reproduce the demonstration

Use Python 3.12 from a clean checkout. The constraints file fixes the output-affecting dependency
versions used for the reviewed v1.0 evidence.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install \
  -c requirements/portfolio-constraints.txt \
  -e ".[dev,ocr,structure]"

pagetrace portfolio-demo portfolio-run-one
pagetrace portfolio-demo portfolio-run-two
```

The command requires a new output directory and promotes the completed result atomically. Compare
`portfolio-manifest.json` from both runs byte for byte:

```bash
# Linux/macOS
cmp portfolio-run-one/portfolio-manifest.json portfolio-run-two/portfolio-manifest.json

# Windows PowerShell
if ((Get-FileHash portfolio-run-one/portfolio-manifest.json).Hash -ne \
    (Get-FileHash portfolio-run-two/portfolio-manifest.json).Hash) { throw "mismatch" }
```

The tagged-release workflow performs this same two-run check before producing distributions.

## What the output proves

`portfolio-manifest.json` is canonical sorted UTF-8 JSON. It records the exact PageTrace and
processor versions, source fingerprint, artifact identities, cited evidence, abstention reason,
retrieval metrics, quality metrics, gate results, limitations, and SHA-256 digests for every
top-level evidence file.

| Demonstrated claim | Machine-verifiable evidence |
| --- | --- |
| The source is immutable and traceable | `document.document_id`, `document.fingerprint`, and the source PDF digest |
| The supported answer is source-grounded | Exact excerpt, page, chunk, offsets, matched terms, rank, and coverage in `demonstrations.supported_answer` |
| No lexical evidence produces no answer | `demonstrations.abstention` records `no_retrieval_hits` and no citations |
| Both judged queries retrieve their relevant page | Two-case retrieval evaluation with Recall, MRR, MAP, and nDCG |
| The fixed portfolio policy passes | Canonical quality suite/report and all eight explicit gate results |
| The current pipeline makes no external model request | `cost.external_requests` and estimated external cost are zero |

The output directory contains:

- `northstar-fy2025.pdf` — deterministic two-page source evidence;
- `artifact-store/` — the verified content-addressed document and derived artifacts;
- `retrieval-dataset.json` and `retrieval-evaluation.json` — relevance judgments and metrics;
- `qa-supported-answer.json` and `qa-abstention.json` — complete canonical retrieval and citation
  provenance for both answer behaviors;
- `quality-suite.json` and `quality-report.json` — fixtures, policy, measurements, and gate results;
- `portfolio-manifest.json` — compact evidence index, digests, and limitations.

## Claims PageTrace does not make

- The two-page synthetic fixture is not a representative benchmark for OCR, retrieval, QA,
  security, fairness, or production reliability.
- The QA baseline selects exact source excerpts. It cannot synthesize, reason across documents, or
  guarantee that an excerpt is true or complete.
- BM25 is a transparent lexical baseline, not semantic retrieval, and no persistent index exists.
- OCR evaluation elsewhere in the project measures supplied fixtures only; the portfolio PDF uses
  sufficient embedded text and therefore demonstrates deterministic OCR routing without claiming
  OCR accuracy.
- Parsers, OCR, and layout dependencies run in-process without hard CPU, memory, or wall-clock
  isolation.
- The web/backend product supports one trusted local operator. It is not a TLS-enabled remote,
  multi-user, or multi-tenant service.

See [SECURITY.md](../SECURITY.md) for the complete trust boundary and
[RELEASING.md](RELEASING.md) for the reviewed release process.
