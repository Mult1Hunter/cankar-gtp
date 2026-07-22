# ADR 0009 - thematic commits, merge-commit PRs

**Status:** accepted, 2026-07 (amends the squash-only policy)

## Context

Squash-only merges (chosen for Verified badges after rebase-merge stripped
signatures) flatten every PR into one commit. For multi-topic PRs this
produces exactly the history the maintainer called out: unrelated changes
fused into a single commit. The overlooked fact: MERGE commits preserve the
original branch commits - locally SSH-signed, therefore Verified - unchanged
in main's DAG, while the merge commit itself is GitHub-signed.

## Decision

- **Branch commits are thematic**: one topic per commit, conventional format
  (already hook-enforced), dependency-ordered so each commit is coherent.
- **Multi-commit PRs land as MERGE commits** (`gh pr merge --merge`);
  single-commit PRs may still squash. Both methods allowed in the ruleset.
- **`required_linear_history` is dropped**; the PR-level view stays linear via
  first-parent traversal (`git log --first-parent main`).

## Consequences

- Main's full DAG has merge bubbles - accepted; kernel-style thematic series
  beat flattened megacommits for archaeology.
- Every branch commit lands on main, so branch discipline tightens: no "wip"
  commits - rewrite the series locally before opening the PR.
- Verified badges: branch commits carry the author's signature; merge commits
  carry GitHub's.
