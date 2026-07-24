# registry/evals/ - frozen evaluation sets

Committed, provenance-stamped, load-bearing - modeled on `registry/datasets/`,
not `works/`. Generated once by `cankar evals holdout-freeze`, then FROZEN:
never hand-edited (a hand-edited holdout is unauditable), never regenerated
except on a deliberate corpus re-merge.

- `holdout.json` - the held-out Cankar set (ADR 0013): whole works with
  per-work content sha256, plus the corpus sha256 those hashes are valid
  against and `also_exclude_urls` (excerpts of held-out works). Phase 3
  conversion excludes ALL of these urls from training; the BPB harness scores
  the held-out works. If the corpus sha changes, re-freeze - stale hashes
  point at the wrong text.
