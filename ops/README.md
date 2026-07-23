# ops/ - repo and infra operations

Run by humans or CI, never imported by cankar/: the commit-msg hook, the
roadmap gate (check-roadmap-pr.sh - ADR 0010), GitHub repo provisioning,
later runpod/ setup + checkpoint-sync (Phase 3) and VPS deploy (Phase 7). Env-driven; no real hostnames (topology lives in the private
meta repo).
