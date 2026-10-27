import { describe, expect, it } from "vitest";
import { DOMAIN, domainOf, isNoise, payload, read } from "@/lib/domains";
import type { BusEvent } from "@/lib/schemas";

const ev = (subject: string, data: BusEvent["data"]): BusEvent => ({ seq: 1, subject, data, received: "2026-10-26T14:30:00Z" });

describe("domains", () => {
  it("maps a subject's head to a domain and everything else to sys", () => {
    expect(domainOf("sense.chat")).toBe("sense");
    expect(domainOf("mod.hello.message.counted")).toBe("mod");
    expect(domainOf("trace.plan")).toBe("trace");
    expect(domainOf("rpc.sys.list")).toBe("rpc");
    expect(domainOf("weird.thing")).toBe("sys");
    expect(Object.keys(DOMAIN)).toEqual(["sense", "brain", "mod", "build", "sys", "out", "trace", "rpc"]);
  });

  it("payload drops the envelope and shortens the rest", () => {
    expect(payload({ id: "x", ts: "t", source: "s", cause: null, hops: 0, text: "hi", n: 2 })).toBe('{"text":"hi","n":2}');
    expect(payload({ text: "a".repeat(200) }, 20)).toHaveLength(20);
  });

  it("reads an event as one plain sentence about what happened", () => {
    const t = (subject: string, data: BusEvent["data"]) => read(ev(subject, data)).text;
    expect(t("sense.chat", { text: "dinner 350", channel: "web" })).toBe("You said “dinner 350”");
    expect(t("sense.chat", { text: "dinner 350", channel: "telegram" })).toBe("You said “dinner 350” on telegram");
    expect(t("out.say", { text: "ok", channel: "web" })).toBe("Replied “ok”");
    expect(t("out.ask", { text: "keep?", choices: ["yes", "no"] })).toBe("Asked you “keep?”");
    expect(t("out.notify", { text: "done" })).toBe("Told you “done”");
    expect(t("trace.plan", { tools: [{ name: "memory.remember" }, { name: "mod.hello.stats" }], rounds: 1 })).toBe(
      "Planned a reply and remembered it, asked hello",
    );
    expect(t("trace.plan", { tools: [], rounds: 1 })).toBe("Planned a reply");
    expect(t("trace.plan", { error: "ConnectError", rounds: 0 })).toBe("Could not answer: ConnectError");
    expect(t("trace.llm", { slot: "planner", provider: "vllm", ok: true })).toBe("Asked the planner model (vllm)");
    expect(t("trace.llm", { slot: "planner", provider: "claude", ok: false })).toBe("Could not reach the planner model (claude)");
    expect(t("sense.feedback", { vote: 1 })).toBe("You gave a thumbs up");
    expect(t("sense.feedback", { answer: "Keep it" })).toBe("You answered “Keep it”");
    expect(t("trace.feedback", { answer: "Keep it" })).toBe("Recorded your answer “Keep it”");
    expect(t("trace.consolidate", { day: "2026-10-25", ok: true, facts: 14 })).toBe("Consolidated 2026-10-25 into 14 facts");
    expect(t("trace.embed", { embedded: 3 })).toBe("Embedded 3 notes");
    expect(t("trace.decide", { picked: 2, scored: 7 })).toBe("Picked 2 of 7 notes for the question");
    expect(t("sys.module.deployed", { name: "hello", image: "img" })).toBe("Started hello");
    expect(t("sys.module.stopped", { name: "hello" })).toBe("Stopped hello");
    expect(t("sys.reconciled", { modules: ["a", "b"] })).toBe("Checked 2 modules at start");
    expect(t("mod.hello.message.counted", { count: 13, day: "2026-10-26" })).toBe("hello: message counted (count 13 · day 2026-10-26)");
  });

  it("keeps the machine's side as meta, shown only in raw mode", () => {
    const plan = read(ev("trace.plan", { tools: [{ name: "memory.remember" }], rounds: 1, cost_usd: 0.0031, latency_ms: 2210 }));
    expect(plan.meta).toBe("trace.plan · 1 round · $0.0031 · 2210 ms");
    expect(read(ev("trace.embed", { embedded: 4, model: "", latency_ms: 12 })).meta).toBe("trace.embed · 12 ms");
    expect(read(ev("sense.chat", { text: "hi", source: "web" }), true)).toEqual({ text: "sense.chat", meta: '{"text":"hi"} · web' });
  });

  it("calls a sweep that found nothing noise, and nothing else", () => {
    expect(isNoise(ev("trace.embed", { embedded: 0 }))).toBe(true);
    expect(isNoise(ev("trace.embed", { embedded: 2 }))).toBe(false);
    expect(isNoise(ev("trace.decide", { scored: 0, picked: 0 }))).toBe(true);
    expect(isNoise(ev("trace.consolidate", { day: "d", ok: true }))).toBe(true);
    expect(isNoise(ev("trace.consolidate", { day: "d", ok: true, facts: 3 }))).toBe(false);
    expect(isNoise(ev("trace.consolidate", { day: "d", ok: false }))).toBe(false);
    expect(isNoise(ev("trace.llm", { slot: "embed", op: "embed" }))).toBe(true);
    expect(isNoise(ev("trace.llm", { slot: "planner" }))).toBe(false);
    expect(isNoise(ev("out.say", { text: "x" }))).toBe(false);
  });
});
