#!/bin/sh
# OpenCode, one non-interactive run on an OpenAI-compatible endpoint (your vLLM or Ollama).
set -eu
mkdir -p "$HOME/.config/opencode"
cat > "$HOME/.config/opencode/opencode.json" <<JSON
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "local": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "local",
      "options": {"baseURL": "$MODEL_ENDPOINT", "apiKey": "${MODEL_KEY:-none}"},
      "models": {"$MODEL_NAME": {"name": "$MODEL_NAME"}}
    }
  },
  "model": "local/$MODEL_NAME",
  "permission": {"edit": "allow", "bash": "allow", "webfetch": "deny"},
  "autoupdate": false,
  "share": "disabled"
}
JSON
exec opencode run --model "local/$MODEL_NAME" "$(cat /work/PROMPT.md)"
