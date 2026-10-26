import { describe, expect, it } from "vitest";
import {
  busEventSchema,
  configReplySchema,
  eventsPageSchema,
  frameSchema,
  healthSchema,
  listReplySchema,
  planTraceSchema,
  sentSchema,
  usageReplySchema,
} from "@/lib/schemas";

describe("the schemas mirror the gateway's pydantic models", () => {
  it("health, sent and the events page are exact", () => {
    expect(healthSchema.parse({ ok: true, name: "Hansen", channel: "web", version: "0.1.0", events: 3, clients: 1, auth: false }).name).toBe("Hansen");
    expect(healthSchema.safeParse({ ok: true, name: "Hansen" }).success).toBe(false);
    expect(sentSchema.parse({ ok: true, id: "x", thread: "web" }).id).toBe("x");
    const page = eventsPageSchema.parse({ ok: true, seq: 2, events: [{ seq: 1, subject: "sense.chat", data: { text: "hi" }, received: "t" }] });
    expect(page.events[0].data.text).toBe("hi");
    expect(busEventSchema.safeParse({ seq: "1", subject: "x", data: {}, received: "t" }).success).toBe(false);
  });

  it("socket frames are a discriminated union: hello, event, stream", () => {
    expect(frameSchema.parse({ type: "hello", seq: 4, name: "Hansen" }).type).toBe("hello");
    const f = frameSchema.parse({ type: "event", seq: 5, subject: "out.say", data: { text: "x" }, received: "t" });
    expect(f.type === "event" && f.subject).toBe("out.say");
    const s = frameSchema.parse({ type: "stream", subject: "stream.llm", data: { cause: "m1", request: "r1", seq: 1, text: "He" } });
    expect(s.type === "stream" && s.data.done).toBe(false);
    expect(frameSchema.safeParse({ type: "stream", subject: "stream.llm", data: { seq: 1 } }).success).toBe(false); // no cause: unmatchable
    expect(frameSchema.safeParse({ type: "bye" }).success).toBe(false);
  });

  it("bus replies are loose: a service may say more than we read", () => {
    const list = listReplySchema.parse({
      ok: true,
      extra: 1,
      modules: [{ name: "hello", status: "running", manifest: { name: "hello", purpose: "p", need: "n" } }],
    });
    expect(list.modules[0].manifest.subscribes).toEqual([]);
    expect(list.modules[0].container).toBeNull();
    expect(listReplySchema.parse({ ok: false, error: "no" }).modules).toEqual([]);
    const cfg = configReplySchema.parse({ ok: true, slots: { planner: { active: "a", providers: { a: { kind: "claude", key_state: "ok" } } } } });
    expect(cfg.slots.planner.task).toBe("complete");
    expect(cfg.budget_usd_month).toBeNull();
    expect(configReplySchema.safeParse({ ok: true, slots: { p: { active: "a", providers: { a: { kind: "x", key_state: "sliver" } } } } }).success).toBe(false);
    expect(usageReplySchema.parse({ ok: true, usd: 1.2 }).calls).toBe(0);
  });

  it("a plan trace defaults what Main leaves out", () => {
    const t = planTraceSchema.parse({ id: "t", cause: "u", reply_id: "a" });
    expect(t.tools).toEqual([]);
    expect(t.error).toBeNull();
    expect(t.rounds).toBe(0);
  });
});
