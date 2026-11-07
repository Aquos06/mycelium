"""Ours, the default coder: a module written file by file through the gateway's `coder` slot.

A local model gets lost in a long agent session, so this is a fixed pipeline of short calls instead, each
with a fresh prompt and one forced tool:

    first round   write_manifest  ->  write_files (app/)  ->  write_files (tests/)
    a change      write_files: the spec, the module's files as they are, the change
    later rounds  write_files: the spec, the files as they are on disk, what failed and its output

Their wording is in prompts/mycelium.py; every prompt is rebuilt from disk, so it stays the same size however
many rounds a build takes. A call that comes back invalid (bad JSON, a path it may not write, a manifest that
does not validate) goes back to the model once more as a tool_result with the error; a reply cut off at max_tokens goes back without its text,
so the retry is no longer than the first try. A gateway error that can pass (a timeout, a refused connection,
an overloaded server) is retried with a backoff, and stops the build (CoderUnavailable) when it does not pass;
one that will not (a prompt too long for the model) fails the round, and the next round tries again. A spent
budget or the per-build call or cost cap stops the build.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import yaml
from pydantic import ValidationError

from mycelium_sdk import (
    Bus,
    ChatMessage,
    CompletionReply,
    CompletionRequest,
    ManifestError,
    NoAnswer,
    Prompt,
    Refused,
    Role,
    Tool,
    ToolResult,
    ToolUse,
    ask,
    validate_manifest,
    validation_message,
)

from ..checks import relative_names
from ..prompts.mycelium import change_prompt, code_prompt, fix_prompt, manifest_prompt, retry_text, tests_prompt
from ..recent import Recent
from ..schemas import CoderContext, CoderResult, ConfigReply, ManifestDraft, Spend, Stage, WriteFiles
from ..workspace import coder_may_write, read_files, write_file
from .base import CoderError, CoderUnavailable

log = logging.getLogger("mycelium.builder.coder")

BUS_MARGIN_S = 5.0
# a gateway error worth retrying: whole words and status codes, never a digit run inside "215000 tokens"
PERMANENT = re.compile(r"too long|context length|maximum context|too many tokens|invalid|not found|unauthori", re.I)
TRANSIENT = re.compile(
    r"timed? ?out|connect(ion|error)?\b|refused|reset|unavailable|overloaded|rate.?limit|temporar|"
    r"\b(429|500|502|503|504|529)\b",
    re.I,
)
ECHO_MAX = 400  # characters of a reply without a tool call that go back to the model


WRITE_MANIFEST = Tool(
    name="write_manifest",
    description="Declare what the module listens to, emits and answers. The builder fills in the rest.",
    args=ManifestDraft,
)
WRITE_FILES = Tool(name="write_files", description="Write whole files into the module folder.", args=WriteFiles)


class MyceliumCoder:
    name = "mycelium"

    def __init__(
        self,
        bus: Bus,
        slot: str = "coder",
        timeout: float = 600.0,
        max_calls: int = 40,
        max_usd: float = 2.0,
        attempts: int = 2,  # a stage's calls before the round gives up on it
        backoff: tuple[float, ...] = (5.0, 20.0),  # waits between retries of a gateway error
    ) -> None:
        self.bus = bus
        self.slot = slot
        self.timeout = timeout
        self.max_calls = max_calls
        self.max_usd = max_usd
        self.attempts = attempts
        self.backoff = backoff
        self._spend = Spend(build_id="")
        self._config = Recent(self._ask_config, ttl=5.0)  # ready() and describe() ask it together

    async def _ask_config(self) -> ConfigReply:
        return await ask(self.bus, "rpc.llm.config", None, ConfigReply, timeout=5)

    async def ready(self) -> str | None:
        try:
            config = await self._config.get()
        except NoAnswer:
            return "the gateway is not answering"
        except Refused as e:
            return f"the gateway could not say how it is set up: {e}"
        if config is None:  # _ask_config answers or raises; never kept as None
            return "the gateway is not answering"
        slot = config.slots.get(self.slot)
        if slot is None:
            return f"the gateway has no {self.slot!r} slot (services/gateway/providers.yaml)"
        provider = slot.providers.get(slot.active)
        if provider is not None and provider.key_state == "missing":
            return f"the {self.slot!r} slot's provider {slot.active!r} has no key"
        return None

    async def describe(self) -> str:
        what = f"Ours: writes the module file by file through the gateway's {self.slot} slot"
        try:
            config = await self._config.get()
        except (NoAnswer, Refused):
            return what
        slot = config.slots.get(self.slot) if config else None
        provider = slot.providers.get(slot.active) if slot else None
        return f"{what}, now {slot.active} ({provider.model})" if slot and provider and provider.model else what

    async def write(self, ctx: CoderContext) -> CoderResult:
        if self._spend.build_id != ctx.build_id:
            self._spend = Spend(build_id=ctx.build_id)
        before = self._spend.model_copy()
        try:
            if ctx.change and (ctx.feedback is None or ctx.feedback.stage == Stage.CODER):
                note = await self._change(ctx)  # nothing judged yet: the change is still the whole task
            elif ctx.fresh or ctx.feedback is None:
                note = await self._fresh(ctx)
            else:
                note = await self._fix(ctx)
        except (CoderError, CoderUnavailable) as e:  # what this round spent stays on the record either way
            e.calls, e.cost_usd = self._spend.calls - before.calls, round(self._spend.cost_usd - before.cost_usd, 6)
            raise
        return CoderResult(
            note=note,
            calls=self._spend.calls - before.calls,
            cost_usd=round(self._spend.cost_usd - before.cost_usd, 6),
            model=self._spend.model,
        )

    # ---- the stages ----------------------------------------------------------------------------------

    async def _fresh(self, ctx: CoderContext) -> str:
        await self._stage(ctx, manifest_prompt(ctx), WRITE_MANIFEST, lambda args: self._write_manifest(ctx, args))
        code = await self._stage(
            ctx,
            code_prompt(ctx, read_files(ctx.dir, "manifest.yaml")),
            WRITE_FILES,
            lambda args: self._write_files(ctx, args, lambda rel: rel.startswith("app/")),
        )
        tests = await self._stage(
            ctx,
            tests_prompt(ctx, read_files(ctx.dir, "manifest.yaml", "app/")),
            WRITE_FILES,
            lambda args: self._write_files(ctx, args, lambda rel: rel.startswith("tests/")),
        )
        return f"wrote the manifest, {_paths(code)}, {_paths(tests)}"

    async def _change(self, ctx: CoderContext) -> str:
        args = await self._stage(
            ctx,
            change_prompt(ctx, read_files(ctx.dir)),
            WRITE_FILES,
            lambda args: self._write_files(ctx, args, lambda rel: True),
        )
        return args.note or f"changed {_paths(args)}"

    async def _fix(self, ctx: CoderContext) -> str:
        args = await self._stage(
            ctx,
            fix_prompt(ctx, read_files(ctx.dir)),
            WRITE_FILES,
            lambda args: self._write_files(ctx, args, lambda rel: True),
        )
        return args.note or f"rewrote {_paths(args)}"

    async def _stage(self, ctx: CoderContext, prompt: Prompt, tool: Tool, apply: Callable[[Any], None]) -> Any:
        """One forced call, validated and applied; an invalid one goes back as a tool_result, once."""
        messages = [ChatMessage(role=Role.USER, content=prompt.user)]
        error = ""
        for _ in range(self.attempts):
            reply = await self._complete(ctx, prompt.system, messages, tool)
            calls = [c for c in reply.tool_calls if c.name == tool.name]
            if not calls:
                error = (
                    "ran out of tokens before calling the tool"
                    if reply.stop_reason == "max_tokens"
                    else f"answered without calling {tool.name}"
                )
                text = reply.text  # not all of it: a cut-off reply would make the retry longer
                messages += [
                    ChatMessage(
                        role=Role.ASSISTANT,
                        content=(text[:ECHO_MAX] + " [...]") if len(text) > ECHO_MAX else text or "(nothing)",
                    ),
                    ChatMessage(role=Role.USER, content=retry_text(error, tool.name)),
                ]
                continue
            call = calls[0]
            raw = call.input
            echo = raw
            try:
                if "_raw" in raw:
                    echo = {}  # cut off at max_tokens: sending it back would make the retry longer still
                    raise ValueError("the arguments were not valid JSON (cut off? write shorter files)")
                args = tool.args.model_validate(raw)
                apply(args)
                return args
            except ValidationError as e:
                error = validation_message(e, tool.name)
            except ValueError as e:
                error = str(e)
            log.info("build %s: %s rejected: %s", ctx.build_id, tool.name, error)
            result = json.dumps({"ok": False, "error": error}, ensure_ascii=False)
            messages += [
                ChatMessage(role=Role.ASSISTANT, content=[ToolUse(id=call.id, name=tool.name, input=echo)]),
                ChatMessage(role=Role.USER, content=[ToolResult(tool_use_id=call.id, content=result)]),
            ]
        raise CoderError(f"{tool.name}: no valid call after {self.attempts} tries: {error}")

    async def _complete(
        self, ctx: CoderContext, system: str, messages: list[ChatMessage], tool: Tool
    ) -> CompletionReply:
        spend = self._spend
        call = CompletionRequest(
            slot=self.slot,
            system=system,
            messages=messages,
            tools=[tool.spec()],
            tool_choice=tool.name,
            cause=ctx.build_id,
            timeout=self.timeout,
        )
        error = ""
        for attempt in range(len(self.backoff) + 1):
            self._check_caps()
            try:
                reply = await ask(self.bus, "rpc.llm.complete", call, CompletionReply, self.timeout + BUS_MARGIN_S)
            except NoAnswer as e:  # the gateway is down or restarting
                error = f"the gateway did not answer ({e})"
            except Refused as e:  # a refusal costs nothing, but it is a call
                spend.calls += 1
                error = str(e)
                if "budget" in error.lower():
                    raise CoderUnavailable(error) from e
                if PERMANENT.search(error) or not TRANSIENT.search(error):  # it would fail the same way again
                    raise CoderError(f"the model refused the request: {error}") from e
            else:
                spend.calls += 1
                spend.cost_usd = round(spend.cost_usd + reply.cost_usd, 6)
                spend.model = reply.model or spend.model
                return reply
            if attempt < len(self.backoff):
                log.warning("build %s: %s; retrying in %ss", ctx.build_id, error, self.backoff[attempt])
                await asyncio.sleep(self.backoff[attempt])
        raise CoderUnavailable(f"the {self.slot!r} model is not answering: {error}")

    def _check_caps(self) -> None:
        """Before every call, retries included. CODER_MAX_USD=0 lets no paid call past the first."""
        spend = self._spend
        if spend.calls >= self.max_calls:
            raise CoderUnavailable(f"the build used all {self.max_calls} of its model calls (CODER_MAX_CALLS)")
        if spend.cost_usd > 0 and spend.cost_usd >= self.max_usd:
            raise CoderUnavailable(f"the build spent ${spend.cost_usd:.2f} of ${self.max_usd:.2f} (CODER_MAX_USD)")

    # ---- writing -------------------------------------------------------------------------------------

    def _write_manifest(self, ctx: CoderContext, draft: ManifestDraft) -> None:
        data = {
            "name": ctx.name,
            "version": "0.1.0",
            "purpose": draft.purpose,
            "need": draft.need,
            "subscribes": draft.subscribes,
            "emits": draft.emits,
            "requests": {r.name: r.model_dump(exclude={"name"}) for r in draft.requests},
            "hooks": {"interval_seconds": draft.interval_seconds},
        }
        problems = relative_names(data, ctx.name)
        if problems:
            raise ValueError("; ".join(problems))
        try:
            validate_manifest(data)
        except ManifestError as e:
            raise ValueError(str(e)) from e
        write_file(ctx.dir, "manifest.yaml", yaml.safe_dump(data, sort_keys=False, allow_unicode=True))

    def _write_files(self, ctx: CoderContext, args: WriteFiles, allowed: Callable[[str], bool]) -> None:
        bad = [f.path for f in args.files if not (coder_may_write(f.path) and allowed(f.path))]
        if bad:
            raise ValueError(f"not yours to write here: {', '.join(bad)}")
        for f in args.files:
            write_file(ctx.dir, f.path, f.content)


def _paths(args: WriteFiles) -> str:
    return ", ".join(f.path for f in args.files)
