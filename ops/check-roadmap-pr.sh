#!/usr/bin/env bash
# Roadmap gate (ADR 0010): mechanical ROADMAP.md checkbox discipline per PR.
#
# 1. Surfaces every ticked ROADMAP line added or edited on this branch:
#    covers [ ]->[x] flips AND in-flight lines added already checked
#    (commit skill section 5). Lines moved unchanged are filtered out;
#    editing a ticked line's text shows as added + a removed-warning - that
#    is expected, a done item changed and deserves a glance.
# 2. FAILS on a flip-down: identical line text changing [x] -> [ ]
#    (done items never become undone silently).
# 3. Warns on removed [x] lines that do not reappear (restructures are
#    legit, erased history is not - the reviewer decides).
# 4. CI mode (PR_BODY set): FAILS unless the PR-template attestation line
#    ("ROADMAP.md checkboxes ticked ...") is present and ticked. CI cannot
#    judge whether the diff completes a deliverable - the gate forces the
#    explicit claim instead. Ticking it on a no-deliverable PR is correct.
#
# Usage:
#   ops/check-roadmap-pr.sh origin/main              # local, before opening a PR
#   ops/check-roadmap-pr.sh <base> <head>            # replay a historical PR
#   PR_BODY="..." ops/check-roadmap-pr.sh <base-sha> # CI (roadmap-gate.yml)
set -euo pipefail

base="${1:?usage: check-roadmap-pr.sh <base-ref> [head-ref]}"
head="${2:-HEAD}"

failures=()
warnings=()

summary() { # human output, teed into the Actions job summary when present
    printf '%s\n' "$1"
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        printf '%s\n' "$1" >>"$GITHUB_STEP_SUMMARY"
    fi
}

contains() {
    local needle=$1 e
    shift
    for e in "$@"; do [[ "$e" == "$needle" ]] && return 0; done
    return 1
}

# --- parse the ROADMAP.md diff (three-dot: the branch's own changes only) ------
added_ticked=()   # text of added "[x]"/"[X]" checkbox lines
added_blank=()    # text of added "[ ]" checkbox lines
removed_ticked=() # text of removed "[x]"/"[X]" checkbox lines

# capture, not process-substitute: a bad ref inside <(...) escapes set -e and
# would silently pass the gate; a failed assignment aborts the script instead
diff_out=$(git diff "$base...$head" -- ROADMAP.md)

checkbox='^[[:space:]]*[-*+][[:space:]]+\[([xX ])\][[:space:]]*(.*)$'
while IFS= read -r line; do
    case "$line" in
    +++* | ---*) continue ;;
    +*) sign='+' ;;
    -*) sign='-' ;;
    *) continue ;;
    esac
    [[ "${line:1}" =~ $checkbox ]] || continue
    state="${BASH_REMATCH[1]}" text="${BASH_REMATCH[2]}"
    if [[ "$sign" == '+' && "$state" != ' ' ]]; then
        added_ticked+=("$text")
    elif [[ "$sign" == '+' ]]; then
        added_blank+=("$text")
    elif [[ "$state" != ' ' ]]; then
        removed_ticked+=("$text")
    fi
done <<<"$diff_out"

# completed = added [x] minus identical removed [x] (lines moved unchanged)
completed=()
for text in "${added_ticked[@]}"; do
    contains "$text" "${removed_ticked[@]}" || completed+=("$text")
done

# removed [x]: flip-down if the same text reappears unticked; warn if gone
for text in "${removed_ticked[@]}"; do
    if contains "$text" "${added_ticked[@]}"; then
        continue # moved, still ticked
    elif contains "$text" "${added_blank[@]}"; then
        failures+=("flip-down (done item unticked): $text")
    else
        warnings+=("removed done item (restructure? verify): $text")
    fi
done

# --- PR-body attestation (CI mode only) ----------------------------------------
# PR_BODY must arrive as an env var, never inline \${{ }} in the workflow -
# inline interpolation of an attacker-controlled body is script injection.
if [[ -n "${PR_BODY+set}" ]]; then
    attest=$(tr -d '\r' <<<"$PR_BODY" |
        grep -E '^[[:space:]]*[-*+][[:space:]]+\[[xX ]\].*ROADMAP\.md checkboxes ticked' |
        head -n1 || true)
    if [[ -z "$attest" ]]; then
        failures+=("PR body is missing the mandatory attestation line - restore the PR-template item 'ROADMAP.md checkboxes ticked ...'")
    elif [[ ! "$attest" =~ ^[[:space:]]*[-*+][[:space:]]+\[[xX]\] ]]; then
        # anchored to the checkbox itself - "[x]" appearing later in the
        # text of a still-unticked line must not pass
        failures+=("attestation unticked - tick '[x] ROADMAP.md checkboxes ticked ...' in the PR body once every completed deliverable is ticked in ROADMAP.md")
    fi
fi

# --- report --------------------------------------------------------------------
summary "## Roadmap gate"
summary ""
if ((${#completed[@]})); then
    summary "Ticked ROADMAP lines added or edited in this PR:"
    for text in "${completed[@]}"; do summary "- [x] $text"; done
else
    summary "No ROADMAP deliverables ticked in this PR."
fi
if ((${#warnings[@]})); then
    summary ""
    for w in "${warnings[@]}"; do summary "WARNING: $w"; done
fi
if ((${#failures[@]})); then
    summary ""
    for f in "${failures[@]}"; do summary "FAIL: $f"; done
    exit 1
fi
