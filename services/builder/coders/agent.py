"""A coding agent as the coder (OpenCode, Claude Code, Codex, Aider): the supervisor runs it, the builder judges it.

The agent works on a copy of the staged folder in a container the supervisor starts (rpc.sys.agent), runs the
tests itself as often as it likes, and hands back the folder as it left it. The builder takes from it only the
files a coder may write, removes the coder files the agent deleted, and then judges the round like any other:
tidy, checks, the sealed verify. A file the supervisor could not bring back (too big, too many) is kept as it
was, never taken for deleted. An agent that changed nothing has failed the round, unless it is the first round
and it ended in an error: then it could not work at all (its model unreachable, no login) and the build stops,
as it does for a supervisor that does not answer or an agent that cannot start (no address, no key).

The agents share one AgentRoster, so asking which of them can run is one rpc.sys.agents, not one per agent.
"""

from __future__ import annotations

import time

from mycelium_sdk import Bus, NoAnswer, Refused, ask

from ..prompts.agent import agent_prompt
from ..schemas import AgentCall, AgentInfo, AgentReply, AgentsReply, CoderContext, CoderResult
from ..workspace import CONTRACT, coder_may_write, read_files, write_file
from .base import CoderError, CoderUnavailable

LOG_MAX = 2000


class AgentRoster:
    """rpc.sys.agents, asked once for every agent coder and kept a few seconds."""

    def __init__(self, bus: Bus, ttl: float = 10.0) -> None:
        self.bus = bus
        self.ttl = ttl
        self._at = 0.0
        self._agents: dict[str, AgentInfo] | None = None

    async def get(self) -> dict[str, AgentInfo] | None:
        """{name: info}, or None when the supervisor does not answer."""
        if self._agents is None or time.monotonic() - self._at > self.ttl:
            try:
                reply = await ask(self.bus, "rpc.sys.agents", None, AgentsReply, timeout=5)
            except (NoAnswer, Refused):
                return None
            self._agents = {a.name: a for a in reply.agents}
            self._at = time.monotonic()
        return self._agents


class AgentCoder:
    def __init__(
        self,
        bus: Bus,
        name: str,
        timeout: float = 1800.0,
        image_build: float = 1200.0,
        roster: AgentRoster | None = None,
    ) -> None:
        self.bus = bus
        self.name = name
        self.timeout = timeout  # one run of the agent
        self.image_build = image_build  # the first run also builds the agent's image
        self.roster = roster or AgentRoster(bus, ttl=0)

    async def ready(self) -> str | None:
        agents = await self.roster.get()
        if agents is None:
            return "the supervisor is not answering"
        info = agents.get(self.name)
        if info is None:
            return f"the supervisor has no agent {self.name!r} (services/supervisor/agent_images/agents.yaml)"
        return None if info.ready else info.reason or "not ready"

    async def write(self, ctx: CoderContext) -> CoderResult:
        prompt = agent_prompt(ctx)
        call = AgentCall(
            agent=self.name,
            name=ctx.name,
            prompt=f"{prompt.system}\n\n{prompt.user}",  # an agent's CLI takes one message
            timeout=self.timeout,
        )
        try:
            reply = await ask(self.bus, "rpc.sys.agent", call, AgentReply, timeout=self.timeout + self.image_build)
        except NoAnswer as e:
            raise CoderUnavailable(f"the supervisor did not answer rpc.sys.agent ({e})") from e
        except Refused as e:
            raise CoderUnavailable(f"{self.name}: {e}") from e
        changed = mirror(ctx, reply.files, reply.skipped, deletes=reply.skipped_more == 0)
        log = reply.output[-LOG_MAX:]
        ending = f"exited {reply.exit_code}" + (" (timed out)" if reply.timed_out else "")
        if not changed and ctx.fresh and reply.exit_code != 0 and not reply.timed_out:
            raise CoderUnavailable(f"{self.name} {ending} and changed nothing:\n{log}")  # it never got going
        if not changed:
            raise CoderError(f"{self.name} {ending} and changed nothing:\n{log}")
        kept = f"; kept as they were (too big to bring back): {', '.join(reply.skipped)}" if reply.skipped else ""
        return CoderResult(
            note=f"{self.name} {ending} after {reply.seconds:g}s: {', '.join(changed)}{kept}",
            log=log,
            model=self.name,
        )


def mirror(
    ctx: CoderContext, files: dict[str, str], skipped: list[str] | None = None, deletes: bool = True
) -> list[str]:
    """The agent's folder onto the staged one, for the paths a coder owns. A path the supervisor skipped is
    still there in the agent's folder: it is not deleted here; nor is anything when the skipped list is not
    complete (`deletes` False). Returns what changed."""
    current = {k: v for k, v in read_files(ctx.dir).items() if k != CONTRACT}
    changed = []
    for rel in sorted(set(current) - set(files) - set(skipped or [])) if deletes else []:
        (ctx.dir / rel).unlink()
        changed.append(f"removed {rel}")
    for rel, text in sorted(files.items()):
        if coder_may_write(rel) and current.get(rel) != text:
            write_file(ctx.dir, rel, text)
            changed.append(rel)
    return changed
