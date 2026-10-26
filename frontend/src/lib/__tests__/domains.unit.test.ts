import { describe, expect, it } from "vitest";
import { DOMAIN, domainOf, payload, read } from "@/lib/domains";
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

  it("reads the common subjects into a sentence and a meta line", () => {
    expect(read(ev("sense.chat", { text: "dinner 350", channel: "telegram" }))).toEqual({ text: "You said “dinner 350”", meta: "sense.chat · telegram" });
    expect(read(ev("out.say", { text: "ok", channel: "web" })).text).toBe("Replied “ok”");
    expect(read(ev("out.ask", { text: "keep?", choices: ["yes", "no"] })).meta).toBe("out.ask · yes / no");
    const plan = read(ev("trace.plan", { tools: [{ name: "memory.remember" }], rounds: 1, cost_usd: 0.0031, latency_ms: 2210 }));
    expect(plan.text).toBe("Planned a reply with memory.remember");
    expect(plan.meta).toBe("trace.plan · 1 round · $0.0031 · 2210 ms");
    expect(read(ev("trace.plan", { error: "ConnectError", rounds: 0 })).text).toBe("Could not answer: ConnectError");
    expect(read(ev("sense.feedback", { vote: 1 })).text).toBe("You gave a thumbs up");
    expect(read(ev("sense.feedback", { answer: "Keep it" })).text).toBe("You answered “Keep it”");
    expect(read(ev("sys.module.deployed", { name: "hello", image: "img" })).text).toBe("hello deployed · img");
    expect(read(ev("mod.hello.message.counted", { count: 3 }))).toEqual({ text: "hello · message.counted", meta: '{"count":3}' });
    expect(read(ev("trace.embed", { embedded: 4, model: "", latency_ms: 12 })).meta).toBe("trace.embed · 12 ms");
  });

  it("raw mode shows the subject and the payload instead", () => {
    expect(read(ev("sense.chat", { text: "hi", source: "web" }), true)).toEqual({ text: "sense.chat", meta: '{"text":"hi"} · web' });
  });
});
