# cankar/tokenizer - Phase 2 Slovene BPE

Trains BPE candidates (rustbpe) on the merged corpus and evaluates per-slice
fertility; the committed report carries the vocab-size decision (ADR 0011).

- `vendored.py` - nanochat's SPLIT_PATTERN + SPECIAL_TOKENS, verbatim,
  drift-checked against the sibling checkout (torch pin conflict makes
  nanochat un-importable here - ADR 0011).
- `train.py` - training + the two-file artifact (tokenizer.pkl AND
  token_bytes.pt; nanochat's base_train asserts on both).
- `evaluate.py` - slices (cankar/literary/wikipedia via source+author),
  fertility, vocab-cost math, morphology probes, snapshot report.
- `cli.py` - `cankar tokenizer train|eval|install`; install copies the
  selected candidate to $NANOCHAT_BASE_DIR/tokenizer/ for Phase 3.

Artifacts land in gitignored `data/tokenizer/<name>/`; provenance manifests
in `registry/datasets/tokenizer/`; report in `registry/reports/`.
