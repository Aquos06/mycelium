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
    expect(t("sys.module.removed", { name: "garden", data: "mycelium-data-garden-v0.1.0-removed-1" })).toBe("Deleted garden");
    expect(t("sys.reconciled", { modules: ["a", "b"] })).toBe("Checked 2 modules at start");
    expect(t("mod.hello.message.counted", { count: 13, day: "2026-10-26" })).toBe("hello: message counted (count 13 · day 2026-10-26)");
  });

  it("reads a build as it goes: where it is, how each round ended, how it ended", () => {
    const t = (subject: string, data: BusEvent["data"]) => read(ev(subject, { name: "water", coder: "opencode", ...data })).text;
    expect(t("build.started", { mode: "new" })).toBe("Started building water");
    expect(t("build.started", { mode: "change" })).toBe("Started changing water");
    expect(t("build.stage", { stage: "coder", round: 2, max_rounds: 6 })).toBe("water: round 2 of 6, the coder is writing");
    expect(t("build.stage", { stage: "verify", round: 1, max_rounds: 6 })).toBe("water: round 1 of 6, building it and running its tests");
    expect(t("build.stage", { stage: "snapshot", round: 2, max_rounds: 6 })).toBe("water: copying its data");
    expect(t("build.progress", { round: 1, max_rounds: 6, passed: false, summary: "tests failed: 1 failed, 4 passed" })).toBe(
      "water: round 1 of 6 failed (tests failed: 1 failed, 4 passed)",
    );
    expect(t("build.progress", { round: 2, passed: true })).toBe("water: round 2 passed");
    expect(t("build.done", { version: "0.1.0" })).toBe("Built water v0.1.0");
    expect(t("build.done", { version: "0.2.0", mode: "change" })).toBe("Changed water v0.2.0");
    expect(t("build.failed", { stage: "tests", error: "no working module after 6 rounds" })).toBe(
      "Building water failed at tests: no working module after 6 rounds",
    );
    expect(read(ev("build.stage", { name: "water", coder: "opencode", stage: "coder", round: 1 })).meta).toBe("build.stage · opencode");
    const chosen = read(ev("build.coder", { coder: "opencode", previous: "mycelium", seed: "mycelium" }));
    expect(chosen).toEqual({ text: "Builds now use opencode instead of mycelium", meta: "build.coder" });
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
    expect(isNoise(ev("out.progress", { ref: "b1", state: "running" }))).toBe(true); // the build.* rows say it
    expect(isNoise(ev("build.stage", { name: "water", stage: "coder" }))).toBe(false);
    expect(isNoise(ev("trace.consolidate", { day: "d", ok: false }))).toBe(false);
    expect(isNoise(ev("trace.llm", { slot: "embed", op: "embed" }))).toBe(true);
    expect(isNoise(ev("trace.llm", { slot: "planner" }))).toBe(false);
    expect(isNoise(ev("out.say", { text: "x" }))).toBe(false);
  });
});
