"""The gateway on the bus.

    rpc.llm.complete   CompletionRequest -> {"ok": true, **CompletionReply}
    rpc.llm.usage      {}                -> {"ok": true, **UsageReply}

Every call publishes an LlmTrace on trace.llm (metadata and cost, never the content: Main's
trace.plan has the content). A slot with a shadow provider runs it after replying: the shadow call
is billed and traced like any other (rule 7 has no exceptions), then compared in a ShadowTrace on
trace.llm.shadow. Over the monthly budget, every call fails fast with ok=false: callers go log-only.
Requests carry the caller's `timeout`; the gateway cancels the vendor call before the caller gives up,
so nothing is billed for a reply nobody receives. Each request runs as its own task, so a slow local
model never queues the cloud calls behind it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine, Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from mycelium_sdk import KV, Bus, Message, validation_message

from .providers import Provider, ProviderError, build_provider
from .schemas import (
    CompletionReply,
    CompletionRequest,
    CompletionResult,
    GatewayConfig,
    LlmTrace,
    ProviderConfig,
    ShadowResult,
    ShadowSide,
    ShadowTrace,
    SlotConfig,
    UsageRecord,
    UsageReply,
)

log = logging.getLogger("mycelium.gateway")


class BudgetExceeded(RuntimeError):
    pass


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


class GatewayService:
    def __init__(
        self,
        bus: Bus,
        config: GatewayConfig,
        kv: KV,
        providers: Mapping[tuple[str, str], Provider] | None = None,
        env: Mapping[str, str] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.bus = bus
        self.config = config
        self.kv = kv
        self.now = now
        self.providers: dict[tuple[str, str], Provider] = dict(providers or {})
        for slot_name, slot in config.slots.items():
            for pname, pcfg in slot.providers.items():
                self.providers.setdefault((slot_name, pname), build_provider(pname, pcfg, env))
        self._tasks: set[asyncio.Task] = set()
        self._usage_lock = asyncio.Lock()  # the counter is read-modify-write; calls finish concurrently

    async def start(self) -> None:
        await self.bus.connect()
        await self.bus.subscribe("rpc.llm.complete", self._wrap(self.complete), queue="gateway")
        await self.bus.subscribe("rpc.llm.usage", self._wrap(self.usage), queue="gateway")

    # ---- dispatch ------------------------------------------------------------------------

    def _wrap(self, fn: Callable[[dict[str, Any]], Coroutine[Any, Any, BaseModel]]):
        async def handler(msg: Message) -> None:
            self._spawn(self._handle(fn, msg))  # return at once: NATS delivers callbacks one at a time

        return handler

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _handle(self, fn: Callable[[dict[str, Any]], Coroutine[Any, Any, BaseModel]], msg: Message) -> None:
        try:
            payload = {"ok": True, **(await fn(msg.data)).model_dump(mode="json")}
        except ValidationError as e:
            payload = {"ok": False, "error": validation_message(e)}
        except (BudgetExceeded, ProviderError, KeyError, ValueError) as e:
            payload = {"ok": False, "error": str(e)}
        except Exception as e:  # never let a handler take the service down
            log.exception("gateway handler failed on %s", msg.subject)
            payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if msg.reply:
            await msg.respond(payload)

    async def drain(self) -> None:
        """Wait for everything in flight, shadow runs included (tests, shutdown)."""
        while pending := [t for t in self._tasks if not t.done()]:  # done tasks leave the set a tick later
            await asyncio.gather(*pending, return_exceptions=True)

    # ---- handlers ------------------------------------------------------------------------

    async def complete(self, data: dict[str, Any]) -> CompletionReply:
        req = CompletionRequest.model_validate(data)
        slot, provider, pcfg = self._resolve(req.slot)

        month = self._month()
        used = await self._usage(month)
        budget = self.config.budget_usd_month
        if used.over(budget):
            await self._trace(req, slot.active, ok=False, error="budget exceeded")
            raise BudgetExceeded(f"budget exceeded: ${used.usd:.2f} of ${budget:.2f} this month")

        result, latency_ms = await self._call(provider, req, slot.active)
        cost = pcfg.cost(result.usage.input_tokens, result.usage.output_tokens)
        await self._bill(month, cost, result)
        await self._trace(req, slot.active, ok=True, result=result, cost=cost, latency_ms=latency_ms)

        if slot.shadow:
            self._spawn(self._shadow(req, result, slot))

        return CompletionReply(**result.model_dump(), provider=slot.active, cost_usd=cost)

    async def usage(self, _data: dict[str, Any]) -> UsageReply:
        month = self._month()
        used = await self._usage(month)
        return UsageReply(**used.model_dump(), month=month, budget_usd_month=self.config.budget_usd_month)

    # ---- internals -----------------------------------------------------------------------

    def _resolve(self, slot_name: str) -> tuple[SlotConfig, Provider, ProviderConfig]:
        slot = self.config.slots.get(slot_name)
        if slot is None:
            raise KeyError(f"unknown slot {slot_name!r}; configured: {sorted(self.config.slots)}")
        return slot, self.providers[(slot_name, slot.active)], slot.providers[slot.active]

    def _month(self) -> str:
        return self.now().strftime("%Y-%m")

    def _hops(self, req: CompletionRequest) -> int:
        return req.hops + 1 if req.cause else 0

    async def _usage(self, month: str) -> UsageRecord:
        return UsageRecord.model_validate(await self.kv.get(f"usage/{month}") or {})

    async def _bill(self, month: str, cost: float, result: CompletionResult) -> None:
        async with self._usage_lock:
            used = await self._usage(month)
            await self.kv.put(f"usage/{month}", used.add(cost, result.usage).model_dump())

    async def _call(
        self, provider: Provider, req: CompletionRequest, name: str, shadow: bool = False
    ) -> tuple[CompletionResult, int]:
        """One vendor call within the caller's timeout. Failures are traced here and raised as ProviderError."""
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(provider.complete(req), timeout=req.timeout)
        except TimeoutError:
            error = f"{name}: timed out after {req.timeout:g}s"
            await self._trace(req, name, ok=False, latency_ms=_ms(t0), error=error, shadow=shadow)
            raise ProviderError(error) from None
        except ProviderError as e:
            await self._trace(req, name, ok=False, latency_ms=_ms(t0), error=str(e), shadow=shadow)
            raise
        return result, _ms(t0)

    async def _trace(
        self,
        req: CompletionRequest,
        provider: str,
        *,
        ok: bool,
        result: CompletionResult | None = None,
        cost: float = 0.0,
        latency_ms: int = 0,
        error: str | None = None,
        shadow: bool = False,
    ) -> None:
        await self.bus.publish(
            "trace.llm",
            LlmTrace(
                cause=req.cause,
                hops=self._hops(req),
                slot=req.slot,
                provider=provider,
                model=result.model if result else None,
                ok=ok,
                latency_ms=latency_ms,
                cost_usd=cost,
                usage=result.usage if result else None,
                stop_reason=result.stop_reason if result else None,
                tool_calls=[c.name for c in result.tool_calls] if result else [],
                tools_offered=[t["name"] for t in req.tools],
                error=error,
                shadow=shadow,
            ),
        )

    async def _shadow(self, req: CompletionRequest, active: CompletionResult, slot: SlotConfig) -> None:
        name = slot.shadow or ""
        provider, pcfg = self.providers[(req.slot, name)], slot.providers[name]
        month = self._month()
        if (await self._usage(month)).over(self.config.budget_usd_month):
            log.info("shadow %s skipped: budget exceeded", name)
            return
        try:
            shadow, latency_ms = await self._call(provider, req, name, shadow=True)
        except ProviderError as e:
            log.warning("shadow provider %s failed: %s", name, e)
            return
        cost = pcfg.cost(shadow.usage.input_tokens, shadow.usage.output_tokens)
        await self._bill(month, cost, shadow)
        await self._trace(req, name, ok=True, result=shadow, cost=cost, latency_ms=latency_ms, shadow=True)

        a = ShadowSide(text=active.text, tool_calls=[c.name for c in active.tool_calls])
        s = ShadowResult(
            provider=name,
            model=shadow.model,
            text=shadow.text,
            tool_calls=[c.name for c in shadow.tool_calls],
            latency_ms=latency_ms,
        )
        await self.bus.publish(
            "trace.llm.shadow",
            ShadowTrace(
                cause=req.cause, hops=self._hops(req), slot=req.slot, active=a, shadow=s, agree=ShadowTrace.agrees(a, s)
            ),
        )
