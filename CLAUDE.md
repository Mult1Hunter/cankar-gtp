# CankarGTP - Claude Code project guide

A from-scratch Slovene micro-LLM (~40M params) trained on public-domain literature,
specialized in Ivan Cankar's prose voice, with a plain->Cankar style-transfer stage.
Plan, phases, risks, go/no-go gates: **ROADMAP.md** (consult when planning phase work).

**This repo is PUBLIC from commit #1** (github.com/Mult1Hunter/cankar-gtp - ADR 0002).
Everything committed is public the moment it's pushed; run the `public-hygiene` skill
before any push.

## Conventions

- **Python via uv.** `uv sync`, `uv run <script>`. Never pip-install globally.
- **JSONL is the interchange format** between all pipeline stages (corpus -> chunks ->
  pairs). No databases in the data pipeline.
- **Nothing heavy in git.** Datasets, checkpoints, weights -> HF Hub / R2
  (`data/`, `checkpoints/` gitignored).
- **Secrets** only via `.env` (see `.env.example`).
- **Commits:** types enforced by the commit-msg hook - use the `commit` skill.
  Tag milestones (`v0.1-tinycankar`, ...).
- **Unicode:** always NFC-normalize Slovene text at ingestion (č/š/ž NFD bugs are a
  known failure mode from past migrations).

## Design invariants (do not violate)

1. **Shared register prompt** - the exact same "plain Slovene" style definition is used
   for de-styling (training-pair generation) AND for knowledge-model drafts at
   inference. This guards against train/inference distribution mismatch.
2. **Eval before claims** - quality statements come from the harness (held-out Cankar
   perplexity, style classifier, LLM meaning-judge), not vibes.
3. **Corpus scripts are published; the merged corpus is not** (Wikipedia CC BY-SA
   share-alike vs. PD Cankar - see ROADMAP Phase 1 licensing note).
4. **MVP gate:** phases 0-4 ship before any serving/orchestration work starts.

## Engineering system (ADR 0003)

- All work lands via PR - never push `main` directly.
- Non-trivial code starts with a **design brief** (`design-brief` skill); at
  new-subsystem scale an architect agent critiques it first. Heuristics ship
  only after real-data calibration with committed fixtures (ADR 0006).
- Run the `corpus-qa` agent on every fresh JSONL shard before it enters the pipeline.
- Every ingested document maps to a works-registry entry (`registry/`, ADR 0004);
  unmatched source records go to triage reports, never silently dropped.
- Validation ladder, provenance rules (MANIFEST.json, prompt hashing): ADR 0003.

## Layout

- **Stage subpackages** (ADR 0005): `cankar/core/` = cross-stage contracts,
  `cankar/corpus/` = Phase-1 pipeline. Each future stage adds one
  `cankar/<stage>/` + `scripts/<stage>/` + `tests/<stage>/` when its phase
  starts - the root never grows.
- `registry/` - works source of truth + coverage reports (ADR 0004),
  `bin/` - env-driven ops helpers, `docs/decisions/` - ADRs (`adr` skill),
  `data/` (gitignored) - working data.
- Target monorepo layout & arrival phases: ADR 0002. Personal notes -> sibling
  private repo `../cankar-gtp-meta`, never here.

## graphify

- For codebase questions run `uv run --group tooling graphify query "<q>"` first
  (also `path`, `explain`); after code changes `graphify update .` (AST-only, free).
- Hook-guard deliberately not installed - revisit at Phase 2 (ADR 0003).

## Current phase

Phase 1 - corpus building. Next: run `scripts/corpus/crawl_wikivir.py`, verify token counts,
add Wikipedia dump ingestion. (Canonical status: ROADMAP checkboxes.)
