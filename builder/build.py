#!/usr/bin/env python3
"""Builder: turns a spec into a module using Claude Code via the Claude Agent SDK.

    python builder/build.py --name expenses --spec specs/expenses.md [--publish]

Steps:
  1. scaffold modules/<name>/ from template/ (unless it already exists)
  2. run a Claude Agent SDK session with cwd = the module folder
  3. independently re-run the module's tests in a fresh process (the agent does not grade itself)
  4. optionally publish build.done / build.failed on the bus

Needs ANTHROPIC_API_KEY. Run it inside the builder container (docker compose run --rm builder ...)
so the agent can only touch the module folder.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("MYCELIUM_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(REPO / "scripts"))

from new_module import scaffold  # noqa: E402

PROMPT = """You are implementing the mycelium module '{name}' in the current directory.

Read CONTRACT.md first and follow it exactly. A reference implementation of a correct module
is in ../hello (read it, do not modify it).

SPEC:
{spec}

Work loop:
1. Edit manifest.yaml for this spec (keep name: {name}).
2. Implement app/main.py (keep the build(**kwargs) + __main__ shape).
3. Write tests in tests/ covering every declared subscription, request and emit.
4. Run `python -m pytest -q tests` and fix until it passes.
5. Validate the manifest:
   python -c "from mycelium_sdk import load_manifest; load_manifest('manifest.yaml')"
Stop when both pass. Do not touch files outside this directory.
"""


async def run_agent(module_dir: Path, name: str, spec: str, max_turns: int, trace_path: Path) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    options = ClaudeAgentOptions(
        cwd=str(module_dir),
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        permission_mode="acceptEdits",
        max_turns=max_turns,
        setting_sources=[],  # reproducible: ignore ~/.claude and project settings
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
    )
    result = "unknown"
    with trace_path.open("w") as trace:
        try:
            async for message in query(prompt=PROMPT.format(name=name, spec=spec), options=options):
                trace.write(json.dumps({"type": type(message).__name__, "repr": repr(message)[:4000]}) + "\n")
                if isinstance(message, ResultMessage):
                    result = getattr(message, "subtype", "done")
        except Exception as e:  # max turns, API errors: still go on to independent verification
            result = f"error: {e}"
    return result


def verify(module_dir: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests"],
        cwd=module_dir,
        capture_output=True,
        text=True,
        timeout=600,
    )
    out = (proc.stdout + proc.stderr)[-4000:]
    if proc.returncode != 0:
        return False, out
    check = subprocess.run(
        [sys.executable, "-c", "from mycelium_sdk import load_manifest; load_manifest('manifest.yaml')"],
        cwd=module_dir,
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        return False, check.stderr[-2000:]
    return True, out


async def publish(event: str, payload: dict) -> None:
    from mycelium_sdk import NatsBus

    bus = NatsBus(os.environ.get("NATS_URL", "nats://localhost:4222"), name="builder")
    await bus.connect()
    await bus.publish(event, payload)
    await bus.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--spec", required=True, type=Path, help="markdown file describing the need")
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--publish", action="store_true", help="publish build.done/build.failed to NATS")
    args = ap.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2

    modules = REPO / "modules"
    module_dir = modules / args.name
    if not module_dir.exists():
        scaffold(args.name, modules)
    spec = args.spec.read_text()
    trace_dir = REPO / "builds"
    trace_dir.mkdir(exist_ok=True)
    trace_path = trace_dir / f"{args.name}-{int(time.time())}.jsonl"

    started = time.time()
    agent_result = asyncio.run(run_agent(module_dir, args.name, spec, args.max_turns, trace_path))
    ok, output = verify(module_dir)
    summary = {
        "name": args.name,
        "agent_result": agent_result,
        "verified": ok,
        "seconds": round(time.time() - started, 1),
        "trace": str(trace_path.relative_to(REPO)),
        "test_output_tail": output[-1500:],
    }
    print(json.dumps(summary, indent=2))
    if args.publish:
        asyncio.run(publish("build.done" if ok else "build.failed", summary))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
