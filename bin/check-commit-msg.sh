#!/usr/bin/env bash
# commit-msg hook: enforce UPPERCASE conventional type (wired via pre-commit).
# Format: TYPE: imperative summary   — types: FEAT FIX DATA TRAIN DOCS CHORE
# Optional lowercase scope and breaking marker: FEAT(corpus)!: ...
# Escape hatches: "Revert ..." (git revert) and "Merge ..." (git plumbing).
set -euo pipefail

first_line=$(head -n1 "$1")
pattern='^(FEAT|FIX|DATA|TRAIN|DOCS|CHORE)(\([a-z0-9-]+\))?!?: .+|^(Revert|Merge) '

if [[ "$first_line" =~ $pattern ]]; then
    exit 0
fi

{
    echo "✗ Bad commit message: '$first_line'"
    echo "  Expected: TYPE: summary   (TYPE ∈ FEAT FIX DATA TRAIN DOCS CHORE, uppercase)"
    echo "  Example:  DATA: add wikipedia dump ingestion"
} >&2
exit 1
