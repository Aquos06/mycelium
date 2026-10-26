#!/usr/bin/env python3
"""mctl: poke the system from your terminal.

    python scripts/mctl.py list
    python scripts/mctl.py deploy hello
    python scripts/mctl.py stop hello
    python scripts/mctl.py logs hello --tail 50
    python scripts/mctl.py health
    python scripts/mctl.py ask hello stats '{"day": "2026-10-18"}'
    python scripts/mctl.py pub sense.chat '{"text": "dinner 350"}'
    python scripts/mctl.py remember mei "moving to Tainan in December" --type person --alias 小美
    python scripts/mctl.py lookup 小美
    python scripts/mctl.py recall "who did I have dinner with last Wednesday?"
    python scripts/mctl.py consolidate 2026-10-14                 # (re)run the nightly consolidation for a day
    python scripts/mctl.py rollup 2026-W42                        # (re)write a week or month summary from its days
    python scripts/mctl.py embed                                  # embed notes and summaries that have no vector yet
    python scripts/mctl.py chat "what did 小美 recommend?"        # talk to Main from the terminal
    python scripts/mctl.py answer <ref> "9pm"                     # answer an out.ask shown by chat
    python scripts/mctl.py usage                                  # gateway spend this month

NATS_URL defaults to nats://localhost:4222 (the port docker compose exposes).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from mycelium_sdk import Envelope, NatsBus

CLI_CHANNEL = "cli"


async def converse(bus: NatsBus, subject: str, payload: dict, thread: str, timeout: float) -> int:
    """Publish one message on the cli channel and print Main's reply (out.say or out.ask) for that thread."""
    got: asyncio.Queue = asyncio.Queue()

    async def on_out(msg):
        if msg.data.get("channel") == CLI_CHANNEL and str(msg.data.get("thread")) == thread:
            await got.put((msg.subject, msg.data))

    await bus.subscribe("out.say", on_out)
    await bus.subscribe("out.ask", on_out)
    await bus.flush()
    await bus.publish(subject, Envelope(source=CLI_CHANNEL).stamp(channel=CLI_CHANNEL, thread=thread, **payload))
    try:
        out_subject, data = await asyncio.wait_for(got.get(), timeout)
    except TimeoutError:
        print(f"no reply within {timeout:.0f}s (is `main` running?)", file=sys.stderr)
        return 1
    print(data.get("text", ""))
    if out_subject == "out.ask":
        print(
            f"\n[choices: {' / '.join(data.get('choices') or [])}]  answer with: mctl answer {data.get('ref')} <choice>"
        )
    return 0


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
        elif args.cmd == "remember":
            payload = {"note": args.note, "fact": {"text": args.text}, "source": "hansen"}
            if args.day:
                payload["fact"]["day"] = args.day
            if args.type:
                payload["type"] = args.type
            if args.alias:
                payload["aliases"] = args.alias
            if args.summary:
                payload["summary"] = args.summary
            reply = await bus.request("rpc.memory.remember", payload, timeout=args.timeout)
        elif args.cmd == "lookup":
            reply = await bus.request("rpc.memory.lookup", {"name": args.name}, timeout=args.timeout)
        elif args.cmd == "recall":
            reply = await bus.request(
                "rpc.memory.recall", {"query": args.query, "budget": args.budget}, timeout=args.timeout
            )
        elif args.cmd == "reindex":
            reply = await bus.request("rpc.memory.reindex", {}, timeout=args.timeout)
        elif args.cmd == "consolidate":
            payload = {"day": args.day} if args.day else {}
            reply = await bus.request("rpc.memory.consolidate", payload, timeout=max(args.timeout, 400.0))
        elif args.cmd == "rollup":
            key = args.key.strip().upper()
            period = "week" if "W" in key else "month"
            reply = await bus.request(
                "rpc.memory.rollup", {"period": period, "key": key}, timeout=max(args.timeout, 400.0)
            )
        elif args.cmd == "embed":
            reply = await bus.request("rpc.memory.embed", {}, timeout=max(args.timeout, 400.0))
        elif args.cmd == "chat":
            return await converse(bus, "sense.chat", {"text": args.text}, args.thread, args.timeout)
        elif args.cmd == "answer":
            return await converse(
                bus, "sense.feedback", {"ref": args.ref, "answer": args.text}, args.thread, args.timeout
            )
        elif args.cmd == "usage":
            reply = await bus.request("rpc.llm.usage", {}, timeout=args.timeout)
        elif args.cmd in ("deploy", "stop"):
            reply = await bus.request(f"rpc.sys.{args.cmd}", {"name": args.name}, timeout=args.timeout)
        elif args.cmd == "logs":
            reply = await bus.request("rpc.sys.logs", {"name": args.name, "tail": args.tail}, timeout=args.timeout)
            if reply.get("ok"):
                print(reply["logs"])
                return 0
        else:
            reply = await bus.request(f"rpc.sys.{args.cmd}", {}, timeout=args.timeout)
        print(json.dumps(reply, indent=2, default=str, ensure_ascii=False))
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
    rem = sub.add_parser("remember", help="append a dated fact to a note (creates the note if needed)")
    rem.add_argument("note", help="note name, e.g. mei")
    rem.add_argument("text", help="the fact; [[links]] allowed")
    rem.add_argument("--day", help="YYYY-MM-DD, default today")
    rem.add_argument("--type", choices=["person", "place", "project", "thing", "routine", "module", "self"])
    rem.add_argument("--alias", action="append", help="repeatable")
    rem.add_argument("--summary", help="replace the note's first paragraph")
    sub.add_parser("lookup").add_argument("name")
    rc = sub.add_parser("recall")
    rc.add_argument("query")
    rc.add_argument("--budget", type=int, default=8)
    sub.add_parser("reindex")
    co = sub.add_parser("consolidate", help="run the nightly consolidation for a day (default yesterday)")
    co.add_argument("day", nargs="?", help="YYYY-MM-DD")
    ro = sub.add_parser("rollup", help="write a week (2026-W43) or month (2026-10) summary from its day summaries")
    ro.add_argument("key")
    sub.add_parser("embed", help="give every note and summary without a vector one (rpc.memory.embed)")
    ch = sub.add_parser("chat", help="send one message to Main on the cli channel and print the reply")
    ch.add_argument("text")
    ch.add_argument("--thread", default="default", help="conversation thread (history is kept per thread)")
    an = sub.add_parser("answer", help="answer a question Main asked (the ref printed by chat)")
    an.add_argument("ref")
    an.add_argument("text")
    an.add_argument("--thread", default="default")
    sub.add_parser("usage", help="gateway spend and calls this month")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
