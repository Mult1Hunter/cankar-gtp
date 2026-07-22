# ADR 0003 — validation ladder for agent-driven development

**Status:** accepted · 2026-07

## Context

Most implementation work in this repo is done by an AI agent (Claude Code), with the
maintainer acting as reviewing tech lead. Agent-produced work needs systematic
verification — human review alone doesn't scale, and "looks right" violates design
invariant #2 (eval before claims).

## Decision

Every change climbs a validation ladder as far as its risk demands:

| Level | Gate | Arrives |
|---|---|---|
| **L0** | mechanical: ruff, gitleaks, commit-msg hook, CI on PRs | now |
| **L1** | tests: pytest; golden-file tests for text cleaning (wikitext fixture → expected text); property tests for the NFC invariant | first pipeline PR |
| **L2** | data contracts: pydantic models per JSONL stage (`CorpusDoc`, `Chunk`, `Pair`) + a validate step; stats-band checks (token counts inside expected ranges — "10× off means the listing is wrong") | Phase 1–2 |
| **L3** | eval gate: harness numbers (held-out perplexity, style classifier, meaning judge) required in any `TRAIN:` PR that claims quality | Phase 2.25 |
| **L4** | human: all work lands via PR; the maintainer merges; the agent never pushes to `main` | now |

**Provenance rules** (invariants made assertable, not remembered):

- every dataset artifact ships a `MANIFEST.json`: generating script's git SHA, source
  snapshot date, content hash, doc/token counts — regenerate and diff to verify
- training/tokenizer configs are committed files, never CLI-only flags; seeds pinned
- the shared register prompt (invariant #1) lives in `prompts/`; its content hash is
  stamped into every generated pair and checked again at inference time

## Tooling adoption map

| Tool | When |
|---|---|
| Graphify (codebase knowledge graph: CLI + skill; hook-guard skipped, revisit Phase 2; no MCP in v0.9.x) | wired at scaffold; earns its keep from Phase 2 |
| CodeQL (python + actions) | active at repo creation |
| `corpus-qa` agent (`.claude/agents/`) | Phase 1, before the first crawl |
| train-monitor watchdog (harness loop + notifications) | Phase 3 cloud runs |
| `prompts/` governance + pair-judge batch script (promptfoo if prompt iterations exceed ~3) | Phase 5 |
| `style-critic` agent — qualitative commentary only, barred from producing quality claims | Phase 6 |
| HF Hub MCP + `hf-publish` skill (model/dataset cards) | Phase 2.5+ |
| claude-code-action PR review; OpenSSF Scorecard | trial after first PRs |

## Rationale

- An invariant you can `assert` beats one you remember; gates catch what review skims.
- Data-pipeline bugs are silent — golden files and contracts make them loud.
- The ladder is phase-matched: no gate exists before the thing it validates does.

## Consequences

- PRs carry ceremony (tests, manifests) — accepted; it is the trust substrate that
  makes agent-written code mergeable on sight.
- Each phase start includes a "which gates activate now" check against this ADR.
