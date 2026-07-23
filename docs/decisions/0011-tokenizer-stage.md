# ADR 0011 - tokenizer stage: vendored nanochat seam, measured vocab choice

**Status:** accepted, 2026-07

## Context

Phase 2 needs a Slovene BPE tokenizer whose artifacts Phase 3 (nanochat's
base_train) consumes unchanged. nanochat cannot be a dependency - it pins
torch==2.9.1 against our >=2.13 - and a sys.path import of the sibling
checkout is unpinned provenance (ADR 0003). The architect critique also
showed the naive artifact and sizing assumptions were wrong: base_train
asserts on token_bytes.pt (produced by nanochat's script, not its library),
and vocab-coupled params are (2 + ceil(L/2)) x V x dim because of per-layer
value embeddings - at 16k vocab that busts a 30M budget at any depth >= 6.

## Decision

New stage `cankar/tokenizer/` (STAGES edit per ADR 0007). The nanochat
coupling surface - SPLIT_PATTERN, SPECIAL_TOKENS, the two-file artifact
recipe - is vendored verbatim (`vendored.py`, provenance-stamped with the
nanochat commit) and drift-checked against the sibling checkout when
present. Candidates {4096, 8192, 16384} are trained on the full merged
corpus (no doc-cap: a deliberate ~5x literary boost vs nanochat defaults,
recorded in the manifest) and compared in a committed snapshot report:
per-slice fertility keyed on (source, author) - cankar / literary /
wikipedia - tail percentiles, digit share, and the real vocab-cost table.
Selection is recorded in the report; `cankar tokenizer install` copies the
winner to $NANOCHAT_BASE_DIR/tokenizer/.

## Rationale

- Vendoring ~50 lines beats a venv dance or an unpinned import; the drift
  test makes staleness visible instead of silent.
- rustbpe==0.1.0 pinned exactly: training determinism is an implementation
  property, guarded by a train-twice fingerprint check in the manifest.
- Whether the Phase 3 budget counts embeddings is NOT decided here; the
  report carries both numbers (ADR 0001's ~30-50M vs the yield-corrected
  ~15-30M ROADMAP line) for the Phase 3 sizing ADR.

## Consequences

- tiktoken here (0.13.x) is newer than nanochat's lock (0.11.0); the pickle
  must be load-verified once in nanochat's venv before Phase 3 starts.
- Re-vendoring is manual: bump NANOCHAT_COMMIT and the constants together.
- Genre classes (verse, drama, OCR) have no metadata field - they are fixture
  coverage, not slice metrics, until a heuristic earns its keep.
