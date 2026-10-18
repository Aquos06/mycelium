#!/usr/bin/env python3
"""mctl: poke the system from your terminal.

    python scripts/mctl.py list
    python scripts/mctl.py deploy hello
    python scripts/mctl.py stop hello
    python scripts/mctl.py logs hello --tail 50
    python scripts/mctl.py health
    python scripts/mctl.py ask hello stats '{"day": "2026-10-18"}'
    python scripts/mctl.py pub sense.chat '{"text": "dinner 350"}'

NATS_URL defaults to nats://localhost:4222 (the port docker compose exposes).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from mycelium_sdk import NatsBus


async def run(args) -> int:
    bus = NatsBus(os.environ.get("NATS_URL", "nats://localhost:4222"), name="mctl")
    await bus.connect()
    try:
        if args.cmd == "pub":
            await bus.publish(args.subject, json.loads(args.data))
            await bus.flush()
            print("published")
            return 0
        if args.cmd == "ask":
            reply = await bus.request(
                f"rpc.mod.{args.module}.{args.action}", json.loads(args.data), timeout=args.timeout
            )
        elif args.cmd in ("deploy", "stop"):
            reply = await bus.request(f"rpc.sys.{args.cmd}", {"name": args.name}, timeout=args.timeout)
        elif args.cmd == "logs":
            reply = await bus.request("rpc.sys.logs", {"name": args.name, "tail": args.tail}, timeout=args.timeout)
            if reply.get("ok"):
                print(reply["logs"])
                return 0
        else:
            reply = await bus.request(f"rpc.sys.{args.cmd}", {}, timeout=args.timeout)
        print(json.dumps(reply, indent=2, default=str))
        return 0 if reply.get("ok") else 1
    finally:
        await bus.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=300.0, help="deploys build images; give them time")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("health")
    for c in ("deploy", "stop"):
        sub.add_parser(c).add_argument("name")
    lg = sub.add_parser("logs")
    lg.add_argument("name")
    lg.add_argument("--tail", type=int, default=100)
    ask = sub.add_parser("ask")
    ask.add_argument("module")
    ask.add_argument("action")
    ask.add_argument("data", nargs="?", default="{}")
    pub = sub.add_parser("pub")
    pub.add_argument("subject")
    pub.add_argument("data", nargs="?", default="{}")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
