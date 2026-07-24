# ADR 0014 - misattribution exclusion via NOT_BY_AUTHOR

**Status:** accepted, 2026-07

## Context

The ADR 0013 holdout audit surfaced texts crawled into Cankar's shard but
written by others (two Vera Albreht memoirs, a critic's essay), carrying
`author="Ivan Cankar"`. ADR 0013 stopgapped them with an eval-side url list,
but they also sit in the merged Cankar TRAINING slice - poisoning Phase 4
continued-pretraining and the style classifier. The merge stamps author from
the shard doc and consults the registry only for dedup, so it had no way to
exclude a work that is simply not by its attributed author. Wikivir (unlike
dLib's `dc:creator`) exposes no structured author metadata, so a crawl-time
detector would be a fragile title heuristic - the ADR 0006 failure class (a
genitive-title sweep already false-positived on Cankar's own `Smrt in pogreb
Jakoba Nesrece`).

## Decision

Add `WorkFlag.NOT_BY_AUTHOR`. The human-curated registry is the source of
truth: a misattributed work is flagged there (author field kept, true author
and rights in `notes`), and `merge.py` drops any shard doc that maps to a
flagged work, before gate/dedup, counting it as `not_by_author`. `coverage.py`
stops counting flagged works as ingested. The eval-side url list is kept but
downgraded from a candidacy filter to an independent last-line assertion
(`cankar_docs` fails loud if one re-appears). This is distinct from cross-
author works that ARE kept under their true author via
`collision_resolution.toml`.

## Rationale

- Enforcement belongs at merge, not crawl: the registry flag is deterministic
  and human-audited; a wikivir title heuristic is fragile and unowned.
- Full-corpus sweep (genitive + person-name + text read) found 5 real records,
  not the 3 the length-banded audit saw - and a Murn letter already correctly
  re-attributed by the collision table (left alone). Enumerated, not detected.
- Flag over deletion: the records must persist so the merge can match and
  exclude them; deleting them would let the shard docs back in.
- Eval keeps its own guard because it reads the merged corpus, never the corpus
  registry (stage independence) - a merge regression must not silently score
  seen text.

## Consequences

- Re-merge: 126,352 docs (-3 from the merged Cankar slice, 249 -> 246);
  set-difference proven to be exactly the 3 audited urls, no cascade.
- Holdout re-frozen: same 50 works and content shas, fraction 5.01% -> 5.02%
  (the 3 left the denominator), new corpus sha - a provenance refresh, not a
  set change.
- Two Albreht memoirs are also in copyright (d. 1982, PD 2053); excluded on the
  attribution flag, rights recorded in notes. Shards keep the raw crawl
  (gitignored, never trains, never published).
- Residual: the class is enumerated, not detected; a future about-subject work
  with no name cue would need the human audit ritual to catch - recorded, not
  mechanized, because a reliable wikivir detector does not exist.
