# PageTrace Roadmap

The roadmap grows PageTrace in evidence-driven increments. Milestone boundaries are plans, not
claims of released functionality.

## Milestone 0 — Project Foundation (complete)

Establish the typed Python package, build metadata, tests, coverage policy, quality tooling,
continuous integration, and project policies required for responsible development.

## Milestone 1 — Secure Deterministic Ingestion (implemented, pending acceptance)

Define a bounded, reproducible ingestion boundary for untrusted documents, including validation,
stable identity, safe paths, limits, and auditable page manifests.

Implementation currently lives on `feat/milestone-1-ingestion` for architectural review. It is not
marked as released. Milestone 2 work has not started.

## Milestone 2 — Text Extraction & OCR

Add measured text extraction and OCR paths with explicit fallback behavior, confidence signals,
and fixtures covering representative document quality.

## Milestone 3 — Structured Document Representation

Represent pages, text spans, layout elements, tables, and their source coordinates without losing
the provenance needed for later evidence display.

## Milestone 4 — Provenance-aware Chunking & Corpus Model

Create chunks and corpus records that retain document, page, region, transformation, and version
lineage while supporting repeatable reconstruction.

## Milestone 5 — Retrieval Baselines & Evaluation

Build transparent retrieval baselines, evaluation datasets, and measurable relevance metrics
before introducing more complex retrieval techniques.

## Milestone 6 — Evidence-grounded QA

Generate answers only from retrieved evidence, preserve source attribution, and define abstention
and unsupported-claim behavior.

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
