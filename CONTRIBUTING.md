# Contributing

Solo project, but issues and PRs are welcome. Setup, conventions, and guardrails:

## Setup

```bash
uv sync                    # Python ≥3.11; installs runtime + dev deps
uv run pre-commit install  # installs pre-commit AND commit-msg hooks
```

## Ground rules

- **Python via uv** — never pip-install globally; run things as `uv run <script>`.
- **Nothing heavy in git** — datasets, checkpoints, and weights live on HF Hub / R2.
  `data/` and `checkpoints/` are gitignored; a pre-commit hook blocks files >1 MB.
- **No secrets** — config via `.env` only (see `.env.example`). gitleaks scans every
  commit locally and every PR in CI.
- **Slovene text is NFC-normalized** at every ingestion point — decomposed č/š/ž
  from past migrations silently corrupt tokenization; use
  `unicodedata.normalize("NFC", text)`.

## Commits

Enforced by the commit-msg hook (`bin/check-commit-msg.sh`):

```
TYPE: imperative summary
```

Allowed types (**uppercase, always**): `FEAT` · `FIX` · `DATA` · `TRAIN` · `DOCS` · `CHORE`.
Examples: `DATA: add wikipedia dump ingestion`, `TRAIN: resume from checkpoint on OOM`.
Optional lowercase scope: `FEAT(corpus): …`. Keep the summary ≤72 chars; add a body
only when the diff doesn't explain itself.

## Pull requests

After the initial commit, `main` only moves via PR. CI must be green:
lint + format (ruff), config checks, and a full-history secrets scan.

Merges are **rebase-only** (linear history, enforced by repo settings): your PR
commits land on `main` verbatim, so keep them atomic and convention-clean. Update
a branch by rebasing onto `main` — never merge `main` into it. Status checks are
strict, so rebase before merging.

## Where facts live (canonical homes)

Every fact has exactly one canonical home; everything else is a pointer to it:
**mechanical config** (hooks, CI, `.gitignore`) wherever enforceable → **this file**
for human workflow → **`docs/decisions/` ADRs** for decisions → **ROADMAP.md** for
plan and status (its checkboxes are the canonical phase state). If you find the same
rule stated twice in prose, one copy is wrong — collapse it into a pointer.

## License

MIT — contributions are accepted under the same license.
