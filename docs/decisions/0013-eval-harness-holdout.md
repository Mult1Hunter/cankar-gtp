# ADR 0013 - evals stage: containment-closed held-out set + vendored BPB

**Status:** accepted, 2026-07

## Context

Phase 2.25 must freeze the measuring stick before Phase 3, or held-out
perplexity is contaminated (risk A4, invariant #2). The obvious design -
hold out whole Cankar works keyed on url - silently fails on this corpus:
the merge kept both individual crtice AND the volumes containing them
(merge.md), and one work appears under both a Wikivir and a dLib url. A
url-keyed holdout would score text that survives inside a kept volume. The
metric is BPB (nanochat's vocab-independent bits-per-byte), whose harness
cannot import nanochat (torch pin, per ADR 0011).

## Decision

New stage `cankar/evals/`. Freeze a whole-work, Wikivir-prose, length-banded
held-out Cankar set with a CONTAINMENT-CLOSURE: a candidate is kept only if
its shingles are < 0.5 contained in every other kept Cankar doc (reusing
`core.textsim`, promoted from corpus dedup). Post-closure a plain url set is
a safe exclusion key. The frozen `registry/evals/holdout.json` is
provenance-stamped (corpus sha256 + per-work content sha + selection params),
modeled on `registry/datasets/` - generated once, never hand-edited. The BPB
metric is vendored verbatim from nanochat with a numerical drift test; the
harness supplies its own deterministic eval batcher (each held-out token
scored exactly once), not nanochat's lossy training loader.

## Rationale

- Containment-closure is the load-bearing fix - it decontaminates against the
  dominant volume-containment and cross-source-twin leaks that a url or
  bare-work_id key both miss (architect critique MF-1/MF-2).
- `registry/evals/` supersedes ADR 0007's pre-registered root `evalsets/`: a
  generated-provenance partition of `registry/` fits the datasets/reports
  model better than a bare root dir.
- The audit is a required step: the committed report lists every held-out
  work for a human to read. It caught three about-Cankar essays misattributed
  as Cankar (see Consequences) - exactly the ADR 0006 failure class.
- BOS id is passed into the batcher (not imported) so evals stays an
  independent stage sibling; real checkpoint loading waits for `cankar/model/`.
- ~5% of the 2.92M-token Cankar slice: stable BPB, minimal Phase 4 cost; the
  eval number predates any post-eval fold-in, so invariant #2 holds.

## Consequences

- Frozen set: 50 works, 146,268 tokens (5.01%). Re-freeze on any corpus
  re-merge (the sha guards this) - stale spans point at the wrong bytes.
- **Corpus finding (loud):** three works ABOUT Cankar by others are
  misattributed `author="Ivan Cankar"` in the merged corpus (memoirs + a
  critic's essay). Excluded from the holdout via a committed list here, but
  they also pollute the Cankar TRAINING slice and need a corpus-stage
  re-attribution + re-merge - tracked as a ROADMAP Phase 1 follow-up.
- Style classifier + LLM-judge remain later Phase 2.25 / Phase 6 deliverables.
