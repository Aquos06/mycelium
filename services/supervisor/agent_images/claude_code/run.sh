#!/bin/sh
# Claude Code, one non-interactive run (-p). It is already in a container of its own, so it may act without
# asking; it runs as `module`, never root.
set -eu
export DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
exec claude -p "$(cat /work/PROMPT.md)" --dangerously-skip-permissions --max-turns "${MAX_TURNS:-60}" \
  ${MODEL_NAME:+--model "$MODEL_NAME"}
