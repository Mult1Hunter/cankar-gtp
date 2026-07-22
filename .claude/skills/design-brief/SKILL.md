---
name: design-brief
description: Architect step before non-trivial code - a short design brief with enumerated data classes, failure modes, and a validation plan. Use BEFORE implementing any new module, script, heuristic, or pipeline stage. Trivial edits are exempt.
---

# Design brief (the architect step)

Post this brief in-chat BEFORE writing the code. It exists because foresight
failures are this project's dominant defect class (ADR 0006: a bibliography
detector shipped against synthetic tests and amputated ~150 poems - one
enumeration question would have caught it).

## The brief (~10 lines, no ceremony)

1. **Goal** - one sentence.
2. **Inputs/outputs** - types, schemas, where artifacts land.
3. **Data classes** - ENUMERATE every kind of input this code will meet
   (for corpus text: prose, verse, drama, catalogs/indexes, OCR noise,
   mixed-language, ...). This line is the whole point: name the class you
   have not thought about yet.
4. **Failure modes + blast radius** - what breaks if this is wrong, and what
   it contaminates downstream (e.g. misattribution poisons the style
   classifier).
5. **Placement** - which stage subpackage/scripts dir (ADR 0005); what
   existing code it reuses.
6. **Validation plan** - what proves it works BEFORE it ships. Heuristics and
   thresholds: the calibration rule (ADR 0006) applies - labeled REAL examples
   of every enumerated class, which then become regression fixtures.
7. **Out of scope** - what this deliberately does not handle, recorded.

## Architect critique (new-subsystem scale)

For phase kickoffs, new pipeline stages, or anything establishing a pattern
others will follow: after drafting the brief, spawn a Plan/architect agent to
challenge it (fresh eyes, read-only) and address its must-fix points before
implementing. Solo-file changes inside an established pattern do not need the
agent - the brief alone suffices.

## Exemptions

Config tweaks, doc edits, mechanical renames, changes fully covered by an
existing brief. When in doubt, write the brief - it costs a minute.
