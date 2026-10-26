import { describe, expect, it } from "vitest";
import { fromEvents, merge, order, waiting, type ChatItem } from "@/lib/chat";
import type { BusEvent } from "@/lib/schemas";

let seq = 0;
const ev = (subject: string, data: BusEvent["data"], received = "2026-10-26T14:30:00Z"): BusEvent => ({ seq: ++seq, subject, data, received });
const env = (id: string, ts: string, cause: string | null = null) => ({ id, ts, source: "x", cause, hops: 0 });

describe("a conversation from the bus", () => {
  it("keeps only the thread on channel web, in turn order", () => {
    const events = [
      ev("sense.chat", { ...env("u1", "2026-10-26T14:00:00Z"), channel: "web", thread: "web", text: "hi" }),
      ev("sense.chat", { ...env("tg", "2026-10-26T14:00:01Z"), channel: "telegram", thread: "web", text: "not mine" }),
      ev("sense.chat", { ...env("u9", "2026-10-26T14:00:02Z"), channel: "web", thread: "other", text: "other thread" }),
      ev("out.say", { ...env("a1", "2026-10-26T14:00:05Z", "u1"), channel: "web", thread: "web", text: "hello" }),
      ev("trace.plan", { ...env("t1", "2026-10-26T14:00:06Z", "u1"), channel: "web", thread: "web", rounds: 1, tools: [] }),
      ev("out.ask", { ...env("q1", "2026-10-26T14:00:07Z"), channel: "web", thread: "web", text: "keep?", choices: ["yes", "no"], ref: "q1" }),
      ev("sense.feedback", { ...env("f1", "2026-10-26T14:00:08Z"), channel: "web", thread: "web", ref: "q1", answer: "yes" }),
    ];
    const items = fromEvents(events, "web");
    expect(items.map((i) => i.kind + ":" + i.id)).toEqual(["user:u1", "trace:t1", "assistant:a1", "ask:q1"]);
    const ask = items[3];
    expect(ask.kind === "ask" && ask.answered).toBe("yes");
  });

  it("skips a malformed message rather than crashing the thread", () => {
    const items = fromEvents([ev("out.say", { channel: "web", thread: "web", text: "no id" }), ev("sense.chat", { ...env("u1", "t"), channel: "web", thread: "web", text: "" })], "web");
    expect(items).toEqual([]);
  });

  it("order keeps a turn's plan and reply right after the message they answer", () => {
    const items: ChatItem[] = [
      { kind: "user", id: "u1", ts: "2026-10-26T14:00:00Z", text: "a" },
      { kind: "user", id: "u2", ts: "2026-10-26T14:00:01Z", text: "b" },
      { kind: "assistant", id: "a1", ts: "2026-10-26T14:00:09Z", text: "A", cause: "u1" },
      { kind: "assistant", id: "a2", ts: "2026-10-26T14:00:08Z", text: "B", cause: "u2" },
      { kind: "trace", id: "t1", ts: "2026-10-26T14:00:10Z", cause: "u1", trace: { id: "t1", cause: "u1", modules: [], tools: [], cost_usd: 0, rounds: 1, error: null, latency_ms: 1 } },
    ];
    expect(order(items).map((i) => i.id)).toEqual(["u1", "t1", "a1", "u2", "a2"]);
  });

  it("merge lets the newest version of an item win and keeps an answer once given", () => {
    const asked: ChatItem = { kind: "ask", id: "q", ts: "2026-10-26T14:00:00Z", text: "?", choices: ["y"], ref: "q", cause: null, answered: "y" };
    const again: ChatItem = { ...asked, answered: null };
    const merged = merge([asked], [again]);
    expect(merged).toHaveLength(1);
    expect(merged[0].kind === "ask" && merged[0].answered).toBe("y");
  });

  it("waiting is true only for a fresh, delivered message of yours with nothing after it", () => {
    const now = Date.parse("2026-10-26T14:00:30Z");
    const you: ChatItem = { kind: "user", id: "u", ts: "2026-10-26T14:00:00Z", text: "a" };
    expect(waiting([you], now)).toBe(true);
    expect(waiting([{ ...you, pending: true }], now)).toBe(false);
    expect(waiting([you, { kind: "assistant", id: "a", ts: "2026-10-26T14:00:05Z", text: "A", cause: "u" }], now)).toBe(false);
    expect(waiting([you], now + 10 * 60_000)).toBe(false);
    expect(waiting([], now)).toBe(false);
  });
});
