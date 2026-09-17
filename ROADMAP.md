# PageTrace Roadmap

The roadmap grows PageTrace in evidence-driven increments. Milestone boundaries are plans, not
claims of released functionality.

## Milestone 0 — Project Foundation (complete)

Establish the typed Python package, build metadata, tests, coverage policy, quality tooling,
continuous integration, and project policies required for responsible development.

## Milestone 1 — Secure Deterministic Ingestion (complete)

Define a bounded, reproducible ingestion boundary for untrusted documents, including validation,
stable identity, safe paths, limits, and auditable page manifests.

The accepted implementation is merged on `main`. It remains unreleased while later development
milestones continue.

## Milestone 2A — Deterministic Text Extraction & OCR Routing (complete)

Extract embedded PDF text with deterministic provenance and immutable derived artifacts. Route
pages with no usable embedded text, sparse embedded text, and image documents explicitly for
future OCR consideration without fabricating OCR output.

## Milestone 2B — OCR Engine & Evaluation (implementation pending acceptance)

Select and integrate a real OCR engine, render only routed pages, and establish representative OCR
fixtures and measured evaluation. Engine choice, model downloads, image preprocessing, language
coverage, and OCR accuracy claims belong here rather than Milestone 2A.

The current implementation uses RapidOCR with bundled PP-OCR models and the CPU ONNX Runtime
backend. PDFium renders only pages selected by the immutable Milestone 2A routing artifact. Exact
text, character-error-rate, and word-error-rate evaluation is available without hidden
normalization. This implementation remains subject to milestone review and acceptance.

## Milestone 3 — Structured Document Representation (implementation pending acceptance)

Represent pages, text spans, layout elements, tables, and their source coordinates without losing
the provenance needed for later evidence display.

The current implementation emits explicit top-left PDF-point or image-pixel coordinates for
embedded words and replay-verified OCR lines, plus line-delimited PDF table grids and positioned
cells. Immutable schema-v1 artifacts retain exact document, text-routing, OCR, processor, backend,
configuration, and content provenance. This implementation remains subject to milestone review
and acceptance.

## Milestone 4 — Provenance-aware Chunking & Corpus Model (implementation pending acceptance)

Create chunks and corpus records that retain document, page, region, transformation, and version
lineage while supporting repeatable reconstruction.

The current implementation builds deterministic page-bounded chunks from positioned text spans,
splits oversized spans into exact character slices, and records source/chunk offsets and bounding
regions for every fragment. Immutable schema-v1 corpus artifacts retain exact structure identity,
content fingerprint, processor, configuration, limits, canonical checksums, and atomic storage.
Readback regenerates the complete corpus from the verified structure source. This implementation
remains subject to milestone review and acceptance.

## Milestone 5 — Retrieval Baselines & Evaluation (implementation pending acceptance)

Build transparent retrieval baselines, evaluation datasets, and measurable relevance metrics
before introducing more complex retrieval techniques.

The current implementation provides a versioned NFKC/case-folded Unicode tokenizer and deterministic
Okapi BM25 ranking with stable tie-breaking and exact corpus, chunk, page, region, processor, and
configuration provenance. Canonical binary-relevance datasets and evaluations report Precision@k,
Recall@k, MRR, MAP, and nDCG. Queries and evaluations are serializable but are not silently retained.
This implementation remains subject to milestone review and acceptance.

## Milestone 6 — Evidence-grounded QA (implementation pending acceptance)

Generate answers only from retrieved evidence, preserve source attribution, and define abstention
and unsupported-claim behavior.

The current implementation provides a deterministic extractive baseline whose answer text is
restricted to exact character slices of BM25 hits. Canonical schema-v1 results embed the complete
retrieval result, attach chunk/rank/offset citations, enforce configurable query-term coverage and
output bounds, and explicitly abstain for no hits, weak evidence, or unusable answer limits. This
implementation remains subject to milestone review and acceptance.

## Milestone 7 — Evaluation & Quality System

Consolidate automated and human evaluation for extraction, retrieval, answers, provenance, safety,
regressions, and cost. Evaluation is cross-cutting: fixtures and metrics begin as soon as behavior
is introduced, well before this dedicated milestone.

## Milestone 8 — Product Backend

Expose stable application workflows, persistence, background execution, observability, and
operational controls behind a deliberately designed backend boundary.

## Milestone 9 — Evidence-first Web Product

Build a web experience centered on inspecting sources, navigating evidence, understanding system
uncertainty, and correcting failures.

## Milestone 10 — Production & Security Hardening

Harden isolation, quotas, privacy, dependency and supply-chain controls, incident readiness,
deployment, and ongoing adversarial testing.

## Milestone 11 — Portfolio v1.0

Deliver a documented, reproducible, evaluated v1.0 portfolio release with clearly stated limits
and demonstrations grounded in real evidence.

Advanced multimodal, vision-language-model, and chart intelligence is optional before v1.0. It
should be introduced only when evaluated user needs and baseline limitations justify its added
complexity, cost, and risk.
