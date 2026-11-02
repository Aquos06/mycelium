#!/bin/sh
# OpenAI's Codex CLI, one non-interactive run (exec) on an endpoint with the Responses API (/v1/responses; recent
# vLLM has it). Its own sandbox is off:
# the container is the sandbox.
set -eu
export MODEL_KEY="${MODEL_KEY:-none}"
mkdir -p "$HOME/.codex"
cat > "$HOME/.codex/config.toml" <<TOML
model = "$MODEL_NAME"
model_provider = "local"

[model_providers.local]
name = "local"
base_url = "$MODEL_ENDPOINT"
env_key = "MODEL_KEY"
wire_api = "responses"
TOML
exec codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check "$(cat /work/PROMPT.md)"
