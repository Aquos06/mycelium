#!/bin/sh
# Aider, one non-interactive run (--message-file) on an OpenAI-compatible endpoint. It runs the tests after each
# edit (--auto-test) and fixes what fails. No git: the builder commits.
set -eu
test_file="tests/test_${MODULE_NAME}.py"
files="manifest.yaml app/main.py $test_file"
for f in tests/test_*.py; do
  [ -e "$f" ] && [ "$f" != "$test_file" ] && [ "$f" != "tests/test_contract.py" ] && files="$files $f"
done
# shellcheck disable=SC2086
exec aider --model "openai/$MODEL_NAME" --openai-api-base "$MODEL_ENDPOINT" --openai-api-key "${MODEL_KEY:-none}" \
  --yes-always --no-git --no-auto-commits --no-check-update --no-analytics --no-show-model-warnings \
  --no-pretty --no-stream --test-cmd "python -m pytest -q tests" --auto-test \
  --read CONTRACT.md --read tests/test_contract.py --message-file /work/PROMPT.md $files
