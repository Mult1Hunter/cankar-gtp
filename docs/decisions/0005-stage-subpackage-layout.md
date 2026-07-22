# ADR 0005 - stage subpackages for the Python monorepo side

**Status:** accepted, 2026-07 (refines the layout table in ADR 0002)

## Context

Phase 1 alone produced five corpus modules and five scripts, all flat under
`cankar/` and `scripts/`. Six more pipeline stages follow (tokenizer, eval
harness, training, pairs, plus `apps/` later); a flat root stops being readable
well before that. Reference projects bracket the options: nanochat (our Phase-3
codebase, ADR 0001) keeps a flat package with stage-PREFIXED script names
(`tok_train`, `base_train`, `chat_sft`); grown-up trainers (OLMo-core, litgpt)
use domain subpackages under a single source package.

## Decision

One package, one venv, one lockfile - partitioned by pipeline stage:

- `cankar/core/` - cross-stage contracts (schema, manifest)
- `cankar/<stage>/` - stage logic (`corpus/` now; `tokenizer/`, `train/`,
  `evals/`, `pairs/` created when their phase starts, per ADR 0002)
- `scripts/<stage>/` - thin entry points, mirroring the package
- `tests/<stage>/` - mirroring both; shared fixtures stay in `tests/fixtures/`
- `configs/<stage>/` - committed run configs (ADR 0003 configs-as-files),
  created from Phase 2 on
- `registry/` stays at root: cross-stage data source of truth, not stage logic

nanochat compatibility is direct: their stage prefixes map 1:1 to our stage
directories (`tok_*` -> `tokenizer/`, `base_*`/`mid_*` -> `train/`,
`chat_sft`/`chat_rl` -> `pairs/`+`train/`), so Phase-3 adaptation is a move,
not a redesign.

## Rationale

- Root directory count stays constant as phases land - one new subdir per
  stage in three predictable places.
- Single-package subpackages avoid uv-workspace packaging ceremony; the one
  real isolation argument (torch only in training installs) is deferred until
  torch actually arrives - a workspace split remains possible then, per stage,
  without touching this layout.
- Matches where successful projects end up (OLMo-core, litgpt) while staying
  mappable to where our training code comes from (nanochat).

## Consequences

- Imports carry the stage: `from cankar.corpus.registry import Registry`.
- Entry points are `uv run scripts/<stage>/<script>.py`.
- If Phase 3 shows torch dependency bleed hurts (CI install times), revisit
  with a uv workspace split - this ADR's partition boundaries already match
  the package boundaries that split would need.
