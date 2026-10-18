"""Module runtime. A module file looks like:

    from mycelium_sdk import Module
    mod = Module()

    @mod.on("sense.chat")
    async def on_chat(msg): ...

    @mod.on_request("stats")
    async def stats(data): return {"count": 3}

    @mod.every(3600)
    async def hourly(): ...

    if __name__ == "__main__":
        mod.run()

The runtime enforces the manifest: you can only emit events you declared,
answer actions you declared, and run intervals you declared.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .bus import Bus, Message, NatsBus
from .manifest import Manifest, load_manifest
from .subjects import OBSERVE, subject_matches

log = logging.getLogger("mycelium.module")

EventHandler = Callable[[Message], Awaitable[None]]
RequestHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
IntervalHandler = Callable[[], Awaitable[None]]

SEVERITIES = ("info", "notice", "alert")


class ContractViolation(RuntimeError):
    pass


class Module:
    def __init__(
        self,
        manifest: Manifest | None = None,
        manifest_path: str | os.PathLike | None = None,
        bus: Bus | None = None,
        data_dir: str | os.PathLike | None = None,
    ) -> None:
        if manifest is None:
            path = manifest_path or os.environ.get("MODULE_MANIFEST", "/app/manifest.yaml")
            manifest = load_manifest(path)
        self.manifest = manifest
        self.name = manifest.name
        self.bus: Bus = bus or NatsBus(os.environ.get("NATS_URL", "nats://localhost:4222"), name=f"mod-{self.name}")
        self.data_dir = Path(data_dir or os.environ.get("MODULE_DATA_DIR", "/data"))
        self._events: list[tuple[str, EventHandler]] = []
        self._requests: dict[str, RequestHandler] = {}
        self._intervals: list[tuple[int, IntervalHandler]] = []
        self._tasks: list[asyncio.Task] = []
        self._started = False

    # ---- registration -------------------------------------------------
    def on(self, subject: str) -> Callable[[EventHandler], EventHandler]:
        if not any(subject_matches(p, subject) or p == subject for p in self.manifest.subscribes):
            raise ContractViolation(f"'{subject}' is not in manifest.subscribes {self.manifest.subscribes}")

        def deco(fn: EventHandler) -> EventHandler:
            self._events.append((subject, fn))
            return fn

        return deco

    def on_request(self, action: str) -> Callable[[RequestHandler], RequestHandler]:
        if action != "health" and action not in self.manifest.requests:
            raise ContractViolation(f"action '{action}' is not in manifest.requests {self.manifest.requests}")

        def deco(fn: RequestHandler) -> RequestHandler:
            self._requests[action] = fn
            return fn

        return deco

    def every(self, seconds: int) -> Callable[[IntervalHandler], IntervalHandler]:
        if seconds not in self.manifest.hooks.interval_seconds:
            raise ContractViolation(
                f"interval {seconds}s is not in manifest.hooks.interval_seconds {self.manifest.hooks.interval_seconds}"
            )

        def deco(fn: IntervalHandler) -> IntervalHandler:
            self._intervals.append((seconds, fn))
            return fn

        return deco

    # ---- outbound -----------------------------------------------------
    async def emit(self, event: str, data: dict[str, Any]) -> None:
        if event not in self.manifest.emits:
            raise ContractViolation(f"event '{event}' is not in manifest.emits {self.manifest.emits}")
        await self.bus.publish(self.manifest.event_subject(event), data)

    async def observe(
        self, type: str, summary: str, data: dict[str, Any] | None = None, severity: str = "info"
    ) -> None:
        """Tell the brain something happened. This is how new modules get noticed without wiring."""
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        await self.bus.publish(
            OBSERVE,
            {
                "source": self.name,
                "type": type,
                "summary": summary,
                "severity_hint": severity,
                "data": data or {},
                "ts": datetime.now(UTC).isoformat(),
            },
        )

    # ---- lifecycle ----------------------------------------------------
    async def start(self) -> None:
        if self._started:
            return
        await self.bus.connect()
        for subject, fn in self._events:
            await self.bus.subscribe(subject, self._guard(fn, subject), queue=f"mod-{self.name}")
        for action, fn in {**self._requests, "health": self._requests.get("health", self._health)}.items():
            await self.bus.subscribe(self.manifest.rpc_subject(action), self._rpc(fn, action), queue=f"mod-{self.name}")
        for seconds, fn in self._intervals:
            self._tasks.append(asyncio.create_task(self._loop(seconds, fn)))
        self._started = True
        await self.bus.publish("sys.module.started", {"name": self.name, "version": self.manifest.version})
        log.info("module %s started", self.name)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        await self.bus.close()
        self._started = False

    def run(self) -> None:
        logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
        asyncio.run(self._main())

    async def _main(self) -> None:
        await self.start()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # pragma: no cover
                pass
        await stop.wait()
        await self.stop()

    # ---- internals ----------------------------------------------------
    async def _health(self, _data: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "name": self.name, "version": self.manifest.version}

    def _guard(self, fn: EventHandler, subject: str) -> EventHandler:
        async def wrapped(msg: Message) -> None:
            try:
                await fn(msg)
            except Exception as e:  # a bad event must never kill the module
                log.exception("handler for %s failed", subject)
                await self.observe("handler.error", f"{subject} handler failed: {e}", severity="notice")

        return wrapped

    def _rpc(self, fn: RequestHandler, action: str) -> EventHandler:
        async def wrapped(msg: Message) -> None:
            try:
                result = await fn(msg.data)
                payload = {"ok": True, **(result or {})}
            except Exception as e:
                log.exception("rpc %s failed", action)
                payload = {"ok": False, "error": str(e)}
            if msg.reply is not None:
                await msg.respond(payload)

        return wrapped

    async def _loop(self, seconds: int, fn: IntervalHandler) -> None:
        while True:
            await asyncio.sleep(seconds)
            try:
                await fn()
            except Exception as e:
                log.exception("interval hook failed")
                await self.observe("hook.error", f"interval hook failed: {e}", severity="notice")
