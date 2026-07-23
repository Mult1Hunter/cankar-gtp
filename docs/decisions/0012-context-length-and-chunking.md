# ADR 0012 - context length T=2048 and chunk-to-fit corpus chunking

**Status:** accepted, 2026-07

## Context

nanochat's current dataloader (BOS-aligned best-fit) packs whole documents
into rows of row_capacity = T+1 and discards the tail of any document it
crops. 55.4% of the Cankar slice exceeds T=2048 (p95 174k chars); unchunked,
a p95 volume keeps ~1-4% of its tokens - the loss concentrates on exactly
the slice this project exists for. The loader docstring recommends the
legacy contiguous loader for "limited data AND long documents", but that
loader is deleted upstream (unreachable from our shallow clone) and predates
the checkpoint-resume state machinery Phase 3 requires (ROADMAP B3).

## Decision

Chunk the merged corpus to documents <= T = 2048 tokens (`cankar tokenizer
chunk`, ADR 0011 stage): recursive split ladder paragraph -> line ->
sentence -> hard, pieces keep their trailing separators so chunks
concatenate byte-exact to the original; chunks carry char spans; budget
means encode_ordinary count excluding BOS (row_capacity = T+1 absorbs it).

## Rationale

- Chunk-to-fit removes the loader's failure premise instead of forking the
  loader; measured residual crop loss over emitted chunks is in the
  committed chunks report (vs ~35% FineWeb reference, vs catastrophic
  unchunked).
- Honesty note: nanochat has no document attention masking - packed rows
  attend across chunks in every design; bestfit's real property is only
  that each chunk's beginning is in-row.
- **chunk_budget == Phase 3 max_seq_len is a coupling invariant.** Chunks
  <= 1024 pack fine into T=2048 rows; the reverse silently loses ~50% per
  chunk. T=1024 stays open for Phase 3 sizing; re-chunking is one cheap
  deterministic run (--budget flag, manifest-tracked).
- Phase 2.25 holdout keys on (url, char span) - spans survive re-chunking,
  chunk_index does not. The chunk run asserts corpus-wide url uniqueness.
- No min-chunk floor or tail-merge: small chunks are bestfit row-fillers;
  the distribution is in the report so this stays evidence-backed.

## Consequences

- If Phase 3 changes max_seq_len, re-chunk before conversion - a stale
  budget is a silent-loss bug, not a tuning knob.
- chunks.jsonl is corpus-ordered; Phase 3 must shuffle before the
  last-parquet-is-val split (warning recorded in token-stats report).
- Hard splits may cut mid-sentence (rare, counted per source in the
  manifest); acceptable - reconstruction and budget are the invariants.
