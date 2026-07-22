# ADR 0008 - code architecture standards

**Status:** accepted, 2026-07

## Context

A code audit answered "are we using enums and proper structure where they
belong?" with: partially. Closed sets were runtime-validated string sets,
results were stringly-keyed dicts, library code raised SystemExit and printed
to stderr, TOML configs were accessed untyped, and no static type checker ran.
mypy's first run immediately found real shadowing (a `triage` parameter
silently shadowed by a local list).

## Standards (all mechanically enforced)

1. **Closed sets are StrEnums** (`Source`, `SourceStatus`, `WorkFlag`) - typo
   safety at authoring time; serialized values unchanged, so committed
   registry JSONL stays byte-compatible (tested).
2. **Result shapes are types**, never stringly dicts: `CrawlStats`,
   `DlibStats`, `EdmRecord` (frozen), `SeedResult`-style returns.
3. **Configs are validated models**: `AuthorConfig` parses authors.toml;
   unknown/missing fields fail at load, not at use.
4. **Library code raises domain exceptions** (`cankar/core/errors.py`);
   `SystemExit` and exit codes exist ONLY in `cli.py` modules. This is what
   makes corpus code reusable from FastAPI (Phase 7) and testable in-process.
5. **Library code logs, never prints**: stdlib `logging` per module; the CLI
   configures handlers. Cloud runs (Phase 3) get parseable logs for free.
6. **One transport policy**: `cankar/core/http.py` `PoliteSession` owns UA,
   timeout, rate limiting; crawlers never construct raw sessions.
7. **Every calibrated threshold is a named constant** with its calibration
   provenance in a docstring (ADR 0006 companion rule).
8. **mypy in CI** (pydantic plugin, `disallow_untyped_defs` on `cankar/`),
   alongside ruff and import-linter. New code arrives typed or CI is red.

## Consequences

- Slightly more ceremony per module (types, exceptions, logger boilerplate).
- Interfaces are self-documenting; refactors are mechanically checkable; the
  Phase 3/7 consumers inherit a library, not a script collection.
