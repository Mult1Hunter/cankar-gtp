---
name: deps-update
description: Local batched dependency update - one consolidated PR instead of per-dependency bot PRs. Run monthly, or when a security alert fires, or when Actions runs show deprecation warnings.
---

# Batched dependency update

Dependabot **version-update PRs are deliberately disabled** (5 bot PRs landed on
day one - that noise is why). Security **alerts** stay on: check the repo
Security tab; Dependabot still opens PRs for actual vulnerabilities - treat
those as FIX-priority, don't batch them.

## Routine - single branch `chore/deps-<yyyy-mm>`, single PR

1. **Python deps:** `uv lock --upgrade && uv sync` - read the lock diff, note
   major bumps.
2. **Hook revs:** `uv run pre-commit autoupdate` - read the rev bumps.
3. **Action pins:** for each `uses:` in `.github/workflows/*.yml`, check the
   latest major:
   `git ls-remote --tags --sort=-v:refname https://github.com/<owner>/<repo> | head`
   Bump majors only after a glance at release notes for breaking input changes.
4. **Deprecation warnings:** open the latest Actions runs and read their
   warnings (Node runtime deprecations, action EOL notices) - these set
   priority even off-cadence.
5. **Verify:** `uv run pre-commit run --all-files` and `uv run ruff check .`
   both clean.
6. **Ship:** one commit - `CHORE: bump dependencies (<yyyy-mm>)` - PR,
   rebase-merge when CI is green. If a bump breaks CI, split ONLY the breaking
   one into its own PR; keep the batch green.
