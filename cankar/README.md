# cankar/ - the one Python package

All importable pipeline logic, stage-partitioned (ADR 0005/0007): `core/` holds
cross-stage contracts; each `<stage>/` (corpus now; tokenizer, evals, train,
pairs later) owns its logic and exactly one `cli.py` registered under the
single `cankar` console entry. `model/` arrives stage-neutral at Phase 3.

Never here: standalone scripts (no scripts/ exists - a "quick script" is a
stage module with a subcommand), notebooks, data, configs.
Import law: stages import only `core` (import-linter enforced).
