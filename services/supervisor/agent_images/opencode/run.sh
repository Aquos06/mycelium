#!/bin/sh
# OpenCode, one non-interactive run on an OpenAI-compatible endpoint (your vLLM or Ollama).
set -eu
# The model's window and how much of it one answer may take. Without a limit OpenCode asks for 32000 output
# tokens, which a 32k model refuses outright ("maximum input length of 768 tokens"). MODEL_CONTEXT, else what the
# server says (vLLM's /v1/models has max_model_len), else 32768; MODEL_MAX_OUTPUT, else a quarter of it.
context="${MODEL_CONTEXT:-$(python3 -c '
import json, os, urllib.request
req = urllib.request.Request(os.environ["MODEL_ENDPOINT"].rstrip("/") + "/models",
                             headers={"Authorization": "Bearer " + os.environ.get("MODEL_KEY", "none")})
try:
    models = json.load(urllib.request.urlopen(req, timeout=10)).get("data") or []
    m = next((m for m in models if m.get("id") == os.environ["MODEL_NAME"]), {})
    print(int(m.get("max_model_len") or 0) or 32768)
except Exception:
    print(32768)
')}"
output="${MODEL_MAX_OUTPUT:-$((context / 4))}"
echo "opencode: $MODEL_NAME, context $context, output $output" >&2
mkdir -p "$HOME/.config/opencode"
cat > "$HOME/.config/opencode/opencode.json" <<JSON
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "local": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "local",
      "options": {"baseURL": "$MODEL_ENDPOINT", "apiKey": "${MODEL_KEY:-none}"},
      "models": {"$MODEL_NAME": {"name": "$MODEL_NAME", "limit": {"context": $context, "output": $output}}}
    }
  },
  "model": "local/$MODEL_NAME",
  "permission": {"edit": "allow", "bash": "allow", "external_directory": "allow", "webfetch": "deny"},
  "autoupdate": false,
  "share": "disabled"
}
JSON
# A permission it would ask for is refused in `run`, and the run ends there: the container is the sandbox, so
# paths outside the module (the SDK, /tmp) are allowed.
exec opencode run --model "local/$MODEL_NAME" "$(cat /work/PROMPT.md)"
