# ADR 0010 - roadmap gate: PR attestation + ticked-deliverable surfacing

**Status:** accepted, 2026-07

## Context

"Every PR that completes a ROADMAP deliverable ticks its checkbox in the same
PR" (ADR 0003, commit skill section 5) was enforced only by a PR-template
line - an honor system. It drifted exactly as honor systems do: merge stage
and Wikipedia ingestion landed ticked, but the CLAUDE.md "Current phase"
mirror went stale, and nothing would catch an unticked deliverable at all.
A rule without a check is a wish.

## Decision

A required CI status check (`roadmap-gate`: workflow -> ops/check-roadmap-pr.sh)
on every PR: the PR-body attestation line must be ticked, newly ticked ROADMAP
lines are listed in the job summary, and a done item flipping [x] -> [ ] fails.

## Rationale

- CI cannot judge whether a code diff completes a deliverable - that is human
  judgment. The gate forces the explicit claim instead; ticking the
  attestation on a no-deliverable PR is correct usage. Known cost accepted:
  a dishonest or careless tick still passes - the gate mechanizes the claim,
  not the judgment.
- Added-[x] parsing (not flip-only): in-flight work arrives as new lines
  already checked (PR #21 calibration case) - a flip parser misses them.
- Separate workflow triggering on `edited`: ticking the body checkbox after
  opening must re-run the gate without re-running the test suite.
- PR body reaches the script via env var, never inline `${{ }}` (script
  injection on a public repo).

## Consequences

- `roadmap-gate` joins required checks in ruleset-main.json; apply with
  `gh api -X PUT repos/<owner>/<repo>/rulesets/<id> --input .github/ruleset-main.json`.
- Deleting/unticking the template line blocks merge; fix is one visible line.
- Ticked-line ratchet: undoing a done item now requires rewording it - which
  is the point.
