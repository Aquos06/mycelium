"""Subject conventions for the mycelium bus.

Events (fire-and-forget, recorded in the JetStream EVENTS stream):
    sense.<source>              inputs: sense.chat, sense.voice, sense.screen, sense.cam, sense.iot
    brain.observe               every module publishes a summary envelope here
    mod.<module>.<event>        module events, e.g. mod.finance.expense.logged
    sys.<event>                 supervisor events, e.g. sys.module.deployed
    build.<event>               builder events, e.g. build.done
    out.<kind>                  outputs: out.say (reply on a thread), out.notify, out.ask (choices), out.ha
    trace.<kind>                decision traces: trace.plan, trace.llm, trace.consolidate, trace.rollup, trace.embed, trace.decide, trace.feedback

Requests (request/reply, NOT stored in the stream so JetStream never answers them):
    rpc.sys.<action>            supervisor: deploy, stop, logs, list, health
    rpc.mod.<module>.<action>   ask a module something
    rpc.memory.<action>         memory service: remember, lookup, recall, reindex
    rpc.llm.<action>            model gateway: complete, usage
"""

EVENT_PREFIXES = ("sense.", "brain.", "mod.", "sys.", "build.", "out.", "trace.")
EVENT_STREAM_SUBJECTS = [p + ">" for p in EVENT_PREFIXES]
OBSERVE = "brain.observe"


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
