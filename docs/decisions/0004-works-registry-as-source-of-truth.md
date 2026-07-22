# ADR 0004 - works registry as source of truth for corpus provenance

**Status:** accepted, 2026-07 (amended 2026-07 for non-authored sources - see Amendment)

## Context

The Wikivir crawl covers 218 Cankar works; dLib.si holds 458 records for the
same author (journal originals, book editions, manuscripts, plus non-text and
in-copyright items). More sources and more authors follow. Without a canonical
list there is no way to say "we have all of X", to prevent title collisions
across authors, or to know where any document came from.

## Decision

A committed, per-author **works registry** (`registry/<author>.jsonl`, pydantic
`WorkRecord` in `cankar/corpus/registry.py`) is the source of truth for every known
work: canonical title, year, genre, aliases, and per-source status
(`ingested`, `candidate`, `skipped-quality`, `skipped-manuscript`,
`skipped-rights`, `missing`). Rules:

- **Registry-first ingestion:** seed the registry from author catalogs (Wikivir
  index + Seznam pages) before crawling; every corpus document must map to a
  registry entry; unmatched source records go to a triage report, never
  silently dropped.
- **Identity:** normalized title (NFC, casefold, punctuation stripped,
  diacritics kept) within one author; publication year disambiguates editions
  and validates plausibility against the author's lifetime.
- **Collision guard:** `scripts/corpus/validate_registry.py` - work_id uniqueness,
  duplicate normalized titles, year ranges, and cross-author title collisions
  flagged for manual confirmation (generic titles like "Jure" collide).
- **Source preference:** hand transcription (wikivir) beats OCR (dlib); dLib
  fills gaps only. OCR ingestion passes cankar/corpus/ocr_clean quality gates.
- `registry/coverage-<author>.md` is generated (`scripts/corpus/report_coverage.py`),
  committed, and answers "what do we have and from where" at a glance.

## Rationale

- Completeness becomes measurable (coverage report) instead of anecdotal.
- Provenance per work survives any pipeline rewrite - it lives in data, not in
  scripts or memory.
- The same structure serves every future author and source (PD authors next).

## Consequences

- Every new source integration starts with registry matching + status
  bookkeeping - small constant overhead per crawler.
- The registry is hand-editable (`notes` never clobbered by tooling); humans
  resolve triage and collision flags.

## Amendment (2026-07) - registry scope is authored literary works

The Wikipedia ingestion stage forced the boundary the original invariant left
implicit. "Every ingested document maps to a works-registry entry" is scoped to
**authored literary works** (the Cankar + PD-author corpus). General-reference
sources without per-work authorship - Wikipedia's ~190k articles - do NOT enter
a per-author works registry; forcing them in would be meaningless.

For such sources the sanctioned provenance path is the committed **dataset
manifest** (`registry/datasets/`, ADR 0007): input dump filename, date, sha256,
license, plus output counts. The "never silently dropped" guarantee still binds,
honored by **skip counts** (every filtered class tallied and recorded in the
manifest) rather than infeasible per-item triage over hundreds of thousands of
redirects and stubs.

CLAUDE.md's engineering-system rule is updated to match: authored-source
documents map to a registry entry; non-authored sources carry dataset-manifest
provenance with per-reason skip counts.
  resolve triage and collision flags.
