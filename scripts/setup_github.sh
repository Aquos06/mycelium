#!/usr/bin/env bash
# One-time GitHub setup: branches, protection rules, environments and their variables.
# Needs the GitHub CLI logged in as the repo owner:  gh auth login
#
#   ./scripts/setup_github.sh owner/mycelium
#
# Note: branch protection on PRIVATE repos needs GitHub Pro/Team. On Free it is skipped with a warning.
set -euo pipefail

REPO="${1:?usage: setup_github.sh owner/repo}"
CHECKS='["lint","unit","integration","e2e"]'

say() { printf '\n== %s\n' "$*"; }

say "branches: dev and stage from main"
MAIN_SHA=$(gh api "repos/$REPO/git/ref/heads/main" -q .object.sha)
for b in dev stage; do
  if gh api "repos/$REPO/git/ref/heads/$b" >/dev/null 2>&1; then
    echo "$b exists"
  else
    gh api "repos/$REPO/git/refs" -f ref="refs/heads/$b" -f sha="$MAIN_SHA" >/dev/null && echo "created $b"
  fi
done
gh api -X PATCH "repos/$REPO" -f default_branch=dev >/dev/null && echo "default branch -> dev"

say "branch protection: PRs + green CI required on main/stage/dev"
for b in main stage dev; do
  if ! gh api -X PUT "repos/$REPO/branches/$b/protection" --input - >/dev/null 2>&1 <<JSON
{
  "required_status_checks": {"strict": true, "contexts": $CHECKS},
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": 0, "dismiss_stale_reviews": true},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": false
}
JSON
  then
    echo "WARN: could not protect $b (private repo on GitHub Free?). Protect it manually or make the repo public."
  else
    echo "protected $b"
  fi
done

say "environments"
ME=$(gh api user -q .id)
mkenv() {
  local name=$1 branch=$2 stack=$3 nats=$4 natsmon=$5 pg=$6 review=$7
  local reviewers='[]'
  [ "$review" = yes ] && reviewers="[{\"type\":\"User\",\"id\":$ME}]"
  gh api -X PUT "repos/$REPO/environments/$name" --input - >/dev/null <<JSON
{"reviewers": $reviewers, "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
  gh api -X POST "repos/$REPO/environments/$name/deployment-branch-policies" -f name="$branch" >/dev/null 2>&1 || true
  for kv in "STACK=$stack" "NATS_PORT=$nats" "NATS_MON_PORT=$natsmon" "PG_PORT=$pg"; do
    k=${kv%%=*}; v=${kv#*=}
    gh api -X POST "repos/$REPO/environments/$name/variables" -f name="$k" -f value="$v" >/dev/null 2>&1 \
      || gh api -X PATCH "repos/$REPO/environments/$name/variables/$k" -f name="$k" -f value="$v" >/dev/null
  done
  echo "$name <- $branch (stack=$stack, nats=$nats, pg=$pg, approval=$review)"
}
#     env          branch stack               nats   mon    pg     approval
mkenv development  dev    mycelium-dev        14222  18222  15432  no
mkenv staging      stage  mycelium-staging    24222  28222  25432  no
mkenv production   main   mycelium            4222   8222   5432   yes

say "next steps (manual)"
cat <<'TXT'
1. Secrets per environment (Settings -> Environments -> <env> -> secrets):
     POSTGRES_PASSWORD (required), ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
2. Install a self-hosted runner on your home box with the label `mycelium`
     (Settings -> Actions -> Runners -> New self-hosted runner). The runner user needs Docker access.
3. Turn deploys on:  gh variable set DEPLOY_ENABLED --body true --repo <owner/repo>
TXT
