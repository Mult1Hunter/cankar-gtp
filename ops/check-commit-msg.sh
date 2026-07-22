#!/usr/bin/env bash
# commit-msg hook: enforce UPPERCASE conventional type + plain-ASCII style.
# Format: TYPE: imperative summary   - types: FEAT FIX DATA TRAIN DOCS CHORE
# Optional lowercase scope and breaking marker: FEAT(corpus)!: ...
# Escape hatches: "Revert ..." (git revert) and "Merge ..." (git plumbing).
set -euo pipefail

first_line=$(head -n1 "$1")
pattern='^(FEAT|FIX|DATA|TRAIN|DOCS|CHORE)(\([a-z0-9-]+\))?!?: .+|^(Revert|Merge) '

if ! [[ "$first_line" =~ $pattern ]]; then
    {
        echo "Bad commit message: '$first_line'"
        echo "  Expected: TYPE: summary   (TYPE one of FEAT FIX DATA TRAIN DOCS CHORE, uppercase)"
        echo "  Example:  DATA: add wikipedia dump ingestion"
    } >&2
    exit 1
fi

# Repo style (CONTRIBUTING.md): plain ASCII punctuation in commit messages -
# no typographic dashes/arrows/middots/ellipsis/curly quotes, no emoji.
if grep -qP '[\x{2013}\x{2014}\x{2018}\x{2019}\x{201C}\x{201D}\x{2026}\x{00B7}]|[\x{2190}-\x{21FF}]|[\x{2600}-\x{27BF}]|[\x{1F000}-\x{1FAFF}]' "$1"; then
    echo "Commit message contains typographic symbols or emoji - plain ASCII only (CONTRIBUTING.md)." >&2
    exit 1
fi
