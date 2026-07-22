# ADR 0006 - design-first controls (architect step + calibration rule)

**Status:** accepted, 2026-07 (extends the ADR 0003 validation ladder upstream)

## Context

The ADR 0003 ladder verifies work AFTER it exists; recovery is strong but
several defects were preventable a minute before coding. Case studies from
Phase 1: a bibliography detector validated only against synthetic data
amputated ~150 poems on the first roster crawl (verse shares short
unpunctuated lines with title lists - an unenumerated input class); an OCR
quality floor guessed at 0.82 missed real garbage scoring 0.822 until
calibrated against a live stream. The failure class is missing foresight -
unenumerated input classes and uncalibrated thresholds - not missing
verification.

## Decision

Three controls, applied BEFORE implementation:

1. **Design brief** (`design-brief` skill): mandatory for any non-trivial new
   code - goal, inputs/outputs, ENUMERATED data classes, failure modes and
   downstream blast radius, placement (ADR 0005), validation plan, out of
   scope. Posted in-chat before the first line of code.
2. **Architect critique**: at new-subsystem / phase-kickoff / pattern-setting
   scale, a fresh-context Plan agent challenges the brief; its must-fix points
   are addressed before implementation.
3. **Calibration rule**: no heuristic or threshold ships without calibration
   against labeled REAL examples of every enumerated class it must separate;
   the calibration set is committed as regression fixtures (e.g.
   `tests/fixtures/poem_*` vs `biblio_*` pinning the verse/catalog boundary).

## Rationale

- Enumeration is where "wait - poems" happens; it cannot be recovered from
  synthetic tests that only encode the classes already imagined.
- Real-data calibration replaced two guessed thresholds with measured ones in
  Phase 1; both guesses had been wrong.
- The critique step reuses what already worked twice in this repo (doc-review
  agent, corpus-qa): fresh context finds what the author's context cannot.

## Consequences

- A minute of ceremony per non-trivial task; agent latency at kickoff scale.
- Briefs are chat artifacts, not committed docs - the durable residue is the
  fixtures, module docstrings stating data classes and calibration provenance,
  and ADRs for pattern-setting choices.
