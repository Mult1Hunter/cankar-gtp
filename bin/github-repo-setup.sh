#!/usr/bin/env bash
# One-shot GitHub repository configuration (idempotent — safe to re-run).
# Applies everything a fresh public repo needs beyond `gh repo create`:
# merge strategy, branch ruleset, security features, Actions permissions, metadata.
#
# Env-driven per bin/ convention (no hardcoded hosts/owners):
#   REPO=owner/name bin/github-repo-setup.sh   # default: current repo's origin
#   DESCRIPTION=... HOMEPAGE=...               # optional overrides
set -euo pipefail

REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
DESCRIPTION="${DESCRIPTION:-A from-scratch Slovene micro-LLM in the voice of Ivan Cankar}"
HOMEPAGE="${HOMEPAGE:-https://nextgen-solutions.xyz}"

echo "Configuring $REPO ..."

# --- merge strategy: rebase-only + linear history (see commit skill §3) ---------
gh repo edit "$REPO" \
  --enable-rebase-merge \
  --enable-squash-merge=false \
  --enable-merge-commit=false \
  --enable-auto-merge \
  --delete-branch-on-merge \
  --enable-wiki=false \
  --enable-projects=false \
  --description "$DESCRIPTION" \
  --homepage "$HOMEPAGE"

# --- discoverability topics (adds are idempotent) -------------------------------
gh repo edit "$REPO" \
  --add-topic llm --add-topic nlp --add-topic gpt --add-topic slovene \
  --add-topic ivan-cankar --add-topic from-scratch --add-topic style-transfer

# --- security features ----------------------------------------------------------
gh api -X PATCH "repos/$REPO" \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled' \
  >/dev/null
gh api -X PUT "repos/$REPO/private-vulnerability-reporting"   # SECURITY.md channel
gh api -X PUT "repos/$REPO/vulnerability-alerts"              # dependabot alerts
gh api -X PUT "repos/$REPO/automated-security-fixes"          # dependabot fixes

# --- Actions: least-privilege default token; PR creation allowed ----------------
# (can_approve_pull_request_reviews=true is required by the monthly
#  pre-commit-autoupdate workflow to open its PR; per-workflow `permissions:`
#  blocks keep everything else read-only.)
gh api -X PUT "repos/$REPO/actions/permissions/workflow" \
  -f default_workflow_permissions=read \
  -F can_approve_pull_request_reviews=true

# --- main ruleset: PR-only, rebase merges, required checks, no force-push -------
# required_approving_review_count is 0: solo maintainer cannot approve own PRs.
if gh api "repos/$REPO/rulesets" -q '.[].name' | grep -qx "main-protection"; then
  echo "ruleset 'main-protection' already exists — skipping"
else
  gh api -X POST "repos/$REPO/rulesets" --input - <<'JSON'
{
  "name": "main-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["rebase"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "checks" },
          { "context": "gitleaks" }
        ]
      }
    }
  ]
}
JSON
fi

echo "Done. Review at: https://github.com/$REPO/settings"
