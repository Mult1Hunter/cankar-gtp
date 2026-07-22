# ADR 0004 - works registry as source of truth for corpus provenance

**Status:** accepted, 2026-07

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
