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
import signal
from typing import Any

from pydantic import Field
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncEngine

from mycelium_sdk import ServiceSettings
from mycelium_sdk.db import CORE_MIGRATIONS, make_engine, migrate
from mycelium_sdk.db.core import events, traces
from mycelium_sdk.subjects import EVENT_STREAM_SUBJECTS

log = logging.getLogger("mycelium.tracer")

# stream.: a reply's text as the model writes it (gateway.stream), read live and never kept: the reply itself
# arrives whole on out.say, and one frame per few tokens would swamp the events table
SKIP_PREFIXES = ("_INBOX", "$JS", "$SYS", "$KV", "_R_", "stream.")


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
    """Appends to `events` and `traces` (mycelium_sdk.db.core) through the async engine."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def record(self, subject: str, raw: bytes, is_request: bool) -> bool:
        if not should_record(subject):
            return False
        data = decode(raw)
        async with self.engine.begin() as conn:
            await conn.execute(
                insert(events).values(
                    subject=subject, source=source_of(subject, data), is_request=is_request, payload=data
                )
            )
            if subject.startswith("trace.") and not is_request:
                await self._record_trace(conn, subject[len("trace.") :], data)
        return True

    async def _record_trace(self, conn, kind: str, data: dict[str, Any]) -> None:
        """trace.* also lands in `traces` (kind, ref = cause, decision). A vote updates the plan it rates."""
        ref = str(data["cause"]) if data.get("cause") is not None else None
        await conn.execute(insert(traces).values(kind=kind, ref=ref, decision=data))
        if kind == "feedback" and data.get("vote") is not None and data.get("ref"):
            await conn.execute(
                update(traces)
                .where(traces.c.kind == "plan", traces.c.decision["reply_id"].astext == str(data["ref"]))
                .values(feedback=int(data["vote"]))
            )

    async def attach(self, nc) -> None:
        async def on_msg(msg):
            try:
                await self.record(msg.subject, msg.data, bool(msg.reply))
            except Exception:
                log.exception("failed to record %s", msg.subject)

        await nc.subscribe(">", cb=on_msg)


class TracerSettings(ServiceSettings):
    database_url: str = Field(validation_alias="DATABASE_URL")
    event_retention_days: int = Field(
        default=365, ge=1, validation_alias="EVENT_RETENTION_DAYS", description="JetStream keeps raw events this long"
    )


async def main() -> None:
    import nats

    s = TracerSettings()
    logging.basicConfig(level=s.log_level)
    engine = make_engine(s.database_url)
    await migrate(engine, CORE_MIGRATIONS)  # the tracer owns events and traces
    nc = await nats.connect(s.nats_url, name="tracer", max_reconnect_attempts=-1)
    await ensure_stream(nc, s.event_retention_days)
    await Recorder(engine).attach(nc)
    log.info("tracer recording")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await nc.drain()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
