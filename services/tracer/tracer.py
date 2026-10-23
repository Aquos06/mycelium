"""Tracer: the system's black box recorder.

- Ensures the JetStream EVENTS stream exists (so events can be replayed later).
- Subscribes to everything on the bus and appends it to Postgres `events`.
  Reply inboxes are skipped; RPC requests are logged (handy for debugging) but
  are never put in the stream, so JetStream never answers a request by mistake.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Any

from mycelium_sdk.subjects import EVENT_STREAM_SUBJECTS

log = logging.getLogger("mycelium.tracer")

SKIP_PREFIXES = ("_INBOX", "$JS", "$SYS", "$KV", "_R_")


def source_of(subject: str, data: dict[str, Any]) -> str:
    if isinstance(data.get("source"), str):
        return data["source"]
    parts = subject.split(".")
    if parts[:2] == ["rpc", "mod"] and len(parts) > 2:
        return parts[2]
    if parts[0] in ("mod", "rpc") and len(parts) > 1:
        return parts[1]
    return parts[0]


def should_record(subject: str) -> bool:
    return not subject.startswith(SKIP_PREFIXES)


def decode(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw.decode(errors="replace")}
    return data if isinstance(data, dict) else {"value": data}


async def ensure_stream(nc, retention_days: int = 365) -> None:
    from nats.js.api import StreamConfig

    js = nc.jetstream()
    cfg = StreamConfig(name="EVENTS", subjects=EVENT_STREAM_SUBJECTS, max_age=retention_days * 24 * 3600)
    try:
        await js.stream_info("EVENTS")
        await js.update_stream(cfg)
        log.info("updated stream EVENTS")
    except Exception:
        await js.add_stream(cfg)
        log.info("created stream EVENTS")


class Recorder:
    def __init__(self, pool) -> None:
        self.pool = pool

    async def record(self, subject: str, raw: bytes, is_request: bool) -> bool:
        if not should_record(subject):
            return False
        data = decode(raw)
        await self.pool.execute(
            "INSERT INTO events (subject, source, is_request, payload) VALUES ($1, $2, $3, $4::jsonb)",
            subject,
            source_of(subject, data),
            is_request,
            json.dumps(data, default=str),
        )
        if subject.startswith("trace.") and not is_request:
            await self.record_trace(subject[len("trace.") :], data)
        return True

    async def record_trace(self, kind: str, data: dict[str, Any]) -> None:
        """trace.* also lands in `traces` (kind, ref = cause, decision). A vote updates the plan it rates."""
        await self.pool.execute(
            "INSERT INTO traces (kind, ref, decision) VALUES ($1, $2, $3::jsonb)",
            kind,
            str(data["cause"]) if data.get("cause") is not None else None,
            json.dumps(data, default=str),
        )
        if kind == "feedback" and data.get("vote") is not None and data.get("ref"):
            await self.pool.execute(
                "UPDATE traces SET feedback = $1 WHERE kind = 'plan' AND decision->>'reply_id' = $2",
                int(data["vote"]),
                str(data["ref"]),
            )

    async def attach(self, nc) -> None:
        async def on_msg(msg):
            try:
                await self.record(msg.subject, msg.data, bool(msg.reply))
            except Exception:
                log.exception("failed to record %s", msg.subject)

        await nc.subscribe(">", cb=on_msg)


async def main() -> None:
    import asyncpg
    import nats

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    nc = await nats.connect(os.environ.get("NATS_URL", "nats://nats:4222"), name="tracer", max_reconnect_attempts=-1)
    await ensure_stream(nc, int(os.environ.get("EVENT_RETENTION_DAYS", "365")))
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=4)
    await Recorder(pool).attach(nc)
    log.info("tracer recording")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await nc.drain()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
