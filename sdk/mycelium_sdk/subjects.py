"""Subject conventions for the mycelium bus.

Events (fire-and-forget, recorded in the JetStream EVENTS stream):
    sense.<source>              inputs: sense.chat, sense.voice, sense.screen, sense.cam, sense.iot
    brain.observe               every module publishes a summary envelope here
    mod.<module>.<event>        module events, e.g. mod.finance.expense.logged
    sys.<event>                 supervisor events, e.g. sys.module.deployed
    build.<event>               builder events: build.started, build.stage, build.progress, build.done, build.failed
    out.<kind>                  outputs: out.say (reply on a thread), out.notify, out.ask (choices), out.ha,
                                out.progress (a job in a thread, one message changed in place)
    trace.<kind>                decision traces: trace.plan, trace.llm, trace.consolidate, trace.rollup, trace.embed, trace.decide, trace.feedback

Live (fire-and-forget, NOT an event: not in the stream, the tracer skips it, nobody keeps it):
    stream.llm                  a reply's text as the model writes it, a frame per few tokens, matched by `cause`

Requests (request/reply, NOT stored in the stream so JetStream never answers them):
    rpc.sys.<action>            supervisor: deploy, verify, agent, agents, stop, logs, list, health
    rpc.build.<action>          builder: start, get, list, coders, default
    rpc.mod.<module>.<action>   ask a module something
    rpc.memory.<action>         memory service: remember, lookup, recall, reindex
    rpc.llm.<action>            model gateway: complete, usage
"""

EVENT_PREFIXES = ("sense.", "brain.", "mod.", "sys.", "build.", "out.", "trace.")
EVENT_STREAM_SUBJECTS = [p + ">" for p in EVENT_PREFIXES]
STREAM_PREFIX = "stream."  # live frames: forwarded to whoever is watching, never recorded
OBSERVE = "brain.observe"

# What the `module` login may do on the bus (services/nats/nats.conf), which is what Module does and no more:
# publish its events, observations and the started notice; answer its own requests; listen to events. Never a
# request of its own (rpc.*), the traces (they carry the planner's memory) or the live model text.
MODULE_PUBLISHES = ("mod.>", OBSERVE, "sys.module.started")
MODULE_LISTENS = ("sense.>", "brain.>", "mod.>", "sys.>", "build.>", "out.>")  # what a manifest may subscribe to
MODULE_ANSWERS = "rpc.mod.>"


def mod_event(module: str, event: str) -> str:
    return f"mod.{module}.{event}"


def mod_rpc(module: str, action: str) -> str:
    return f"rpc.mod.{module}.{action}"


def sys_rpc(action: str) -> str:
    return f"rpc.sys.{action}"


def subject_matches(pattern: str, subject: str) -> bool:
    """NATS-style matching: '*' matches one token, '>' matches one or more trailing tokens."""
    p_tokens = pattern.split(".")
    s_tokens = subject.split(".")
    for i, p in enumerate(p_tokens):
        if p == ">":
            return len(s_tokens) > i
        if i >= len(s_tokens):
            return False
        if p != "*" and p != s_tokens[i]:
            return False
    return len(p_tokens) == len(s_tokens)
