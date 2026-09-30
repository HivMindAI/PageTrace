# Milestone 12 — Real-World Evaluation & Reliability

## Status

Planned. Nothing in this document is an accepted capability or a claim about general document
accuracy. PageTrace v1.0.1 remains the current accepted release.

## Objective

Evaluate the released deterministic pipeline on representative real documents, publish bounded
and reproducible findings, and convert measured failure classes into regression coverage before
adding more complex retrieval or model-assisted generation.

The milestone evaluates the existing pipeline rather than changing its evidence contract:

```text
ingestion -> extraction/OCR -> structure -> corpus -> BM25 retrieval -> extractive QA -> quality
```

## Non-goals

- Training or fine-tuning OCR, language, or vision-language models.
- Adding embeddings, vector databases, hybrid retrieval, or persistent indexes.
- Generating abstractive answers or synthesizing claims across excerpts.
- Claiming support for unmeasured languages, layouts, domains, or deployment environments.
- Committing confidential, personal, copyrighted-without-permission, or otherwise restricted
  source documents to the repository.
- Treating wall-clock or memory observations from one machine as deterministic artifacts.

## Phase 12A — Corpus and labels

Create a benchmark manifest whose entries identify source bytes by SHA-256 without depending on a
filename or local path. Each entry records:

- a stable case identifier and exact document digest;
- media type, page count, language, and document/layout cohorts;
- source and license information plus one of `redistributable`, `local_only`, or `excluded`;
- whether OCR text, retrieval relevance, answer correctness, and citation relevance labels exist;
- label provenance and review status without reviewer identity or free-text personal information;
  and
- explicit exclusions or known limitations.

The initial corpus must contain at least 30 documents. Each of these cohorts must have at least five
members, although one document may belong to multiple cohorts:

- born-digital PDF;
- scanned PDF;
- photographed PNG or JPEG page;
- multi-column layout;
- table-heavy document; and
- degraded, skewed, or rotated source.

OCR ground truth must cover at least 50 representative pages. Retrieval and QA labels must cover at
least 60 questions, including answerable, ambiguous, and no-evidence cases. Restricted document
bytes remain outside version control; their manifest metadata and results must not reveal source
content.

## Phase 12B — Frozen baseline

Run every eligible case using one documented PageTrace release, dependency lock/constraints,
configuration, and platform record. A single benchmark command must write an atomic output
directory containing:

- `benchmark-manifest.json` — corpus identity, case metadata, configuration, and environment;
- `case-results.jsonl` — bounded per-document and per-question outcomes;
- `metrics.json` — aggregate and cohort-level metrics with sample counts;
- `failures.json` — stable failure categories and affected case identifiers;
- `SUMMARY.md` — a human-readable report with scope and claim limitations; and
- `SHA256SUMS` — digests for every emitted benchmark artifact.

The baseline reports, when labels are present:

- ingestion success and typed rejection rates;
- OCR exact match, CER, and WER;
- retrieval Precision@k, Recall@k, MRR, MAP, and nDCG;
- answer correctness, abstention behavior, citation precision/recall, and false-answer rate;
- provenance and artifact-readback failures; and
- observational stage duration, peak memory, and output-size measurements.

Missing labels or undersized cohorts produce an explicit `incomplete` result. They never become a
zero metric or an implicit pass.

## Phase 12C — Reliability improvements

Freeze the baseline and declare quality thresholds before changing pipeline behavior. Prioritize
failures by frequency, severity, and effect on evidence correctness. Every accepted fix must add a
redistributable minimal reproduction or a privacy-safe derived fixture, demonstrate the failure on
the baseline version, and pass the existing full validation matrix.

Reruns compare the same benchmark identity and configuration. Corpus, label, configuration, or
dependency changes create a new benchmark identity and cannot silently replace a prior baseline.

## Required gates

Milestone acceptance requires:

- all corpus and label minimums in Phase 12A;
- a reproducible baseline artifact set matching the contract in Phase 12B;
- predeclared minimum metric and directional-regression thresholds;
- zero mechanically invalid citations in answered cases;
- explicit separation of answer correctness from citation validity;
- CI failure for deterministic quality regressions and `incomplete` for missing evidence;
- privacy review of the manifest and generated reports; and
- an acceptance record listing the exact benchmark identity, results, limitations, and retained
  failure classes.

Threshold values are intentionally not invented in this plan. They must be set from the frozen
baseline and documented before Phase 12C changes are measured.

## First implementation slice

The first code change should implement only the canonical benchmark-manifest schema, validation,
identity, safe loading, and tests. It should not run the document pipeline yet. That narrow slice
establishes the privacy and reproducibility boundary on which the runner and reports will depend.
