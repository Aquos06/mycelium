"""The builder (ARCHITECTURE §7): turns a spec Hansen approved into a running module.

__main__.py     entrypoint: `python -m builder`
settings.py     GROWN_DIR, TEMPLATE_DIR, EXAMPLE_DIR, BUILDER_CODER, the rounds, the caps, the timeouts
schemas/        every shape the builder speaks: rpc.build.*, the record, the events, a coder's round, and
                what it asks the supervisor and the gateway
service.py      BuilderService: rpc.build.* handlers, the queue, the worker, recovery after a restart
pipeline.py     one build: scaffold -> rounds of coder, checks, verify -> promote, commit -> deploy
workspace.py    GROWN_DIR/.staging/<name>: scaffold, the paths a coder may write, tidy, promote
checks.py       the pinned manifest and the static rules, before anything runs
contract.py     tests/test_contract.py, the builder's own test next to the coder's
prompts/        what the coders read: the brief every coder gets (CONTRACT.md, the SDK in a page, hello as
                the example), and each coder's own prompts, built as the SDK's Prompt(system, user)
repo.py         GROWN_DIR as a git repo: one commit and one tag per build
coders/         who writes the files: `mycelium` (ours, through the gateway's coder slot) by default, or a
                coding agent (opencode, claude_code, codex, aider) the supervisor runs in a container of its own
"""
