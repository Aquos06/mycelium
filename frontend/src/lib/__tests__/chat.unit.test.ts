import { describe, expect, it } from "vitest";
import { fromEvents, jobOf, merge, newer, order, pendingTurn, settle, updatedAt, waiting, type ChatItem, type ProgressItem } from "@/lib/chat";
import { hhmm } from "@/lib/format";
import { buildRecordSchema, type BusEvent } from "@/lib/schemas";

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
    expect(pendingTurn([you], now)).toBe("u"); // the cause a reply being written streams under
    expect(pendingTurn([], now)).toBeNull();
    expect(waiting([{ ...you, pending: true }], now)).toBe(false);
    expect(waiting([you, { kind: "assistant", id: "a", ts: "2026-10-26T14:00:05Z", text: "A", cause: "u" }], now)).toBe(false);
    expect(waiting([you], now + 10 * 60_000)).toBe(false);
    expect(waiting([], now)).toBe(false);
  });

  it("folds a job's updates into one card: where it first showed, with the newest picture", () => {
    const step = (text: string, state = "active") => ({ text, state });
    const progress = (id: string, ts: string, seq: number, state: string, title: string) =>
      ev("out.progress", { ...env(id, ts, "stage-event"), channel: "web", thread: "web", ref: "b1", seq, state, title, steps: [step(title)], text: title });
    const events = [
      ev("out.say", { ...env("a1", "2026-10-26T14:00:00Z"), channel: "web", thread: "web", text: "Building water." }),
      progress("p1", "2026-10-26T14:00:01Z", 1, "running", "round 1"),
      progress("p3", "2026-10-26T14:00:09Z", 3, "running", "round 2"),
      progress("p2", "2026-10-26T14:00:05Z", 2, "running", "checks"), // arrived late
      ev("sense.chat", { ...env("u2", "2026-10-26T14:00:07Z"), channel: "web", thread: "web", text: "how long?" }),
    ];
    const items = fromEvents(events, "web");
    expect(items.map((i) => i.id)).toEqual(["a1", "progress:b1", "u2"]);
    const card = items[1];
    expect(card.kind === "progress" && [card.title, card.seq, card.ts]).toEqual(["round 2", 3, "2026-10-26T14:00:01Z"]);
    expect(card.kind === "progress" && [jobOf(card), updatedAt(card)]).toEqual(["b1", "2026-10-26T14:00:09Z"]); // its last word

    // the finished card wins over any running one, stored or on the bus, whatever its seq
    const done = fromEvents([...events, progress("p9", "2026-10-26T14:01:00Z", 0, "done", "Built water")], "web")[1];
    expect(done.kind === "progress" && [done.state, done.title, done.ts]).toEqual(["done", "Built water", "2026-10-26T14:00:01Z"]);
    const merged = merge([done], fromEvents(events, "web")).find((i) => i.id === "progress:b1");
    expect(merged?.kind === "progress" && merged.state).toBe("done");
    expect(newer(card as Extract<ChatItem, { kind: "progress" }>, { ...(card as Extract<ChatItem, { kind: "progress" }>), seq: 2, title: "old" }).title).toBe("round 2");
  });

  it("ends a card that missed its last update the way the builder says the build did", () => {
    const card: ProgressItem = {
      kind: "progress",
      id: "progress:b1",
      ts: "2026-10-26T14:00:01Z",
      cause: null,
      title: "Building water",
      state: "running",
      seq: 4,
      steps: [
        { text: "Round 1: tests failed", state: "failed" },
        { text: "Round 2 of 6: fixing what failed", state: "active", since: "2026-10-26T14:03:00Z" },
        { text: "Save it", state: "pending" },
        { text: "Start it", state: "pending" },
      ],
    };
    const record = (fields: Record<string, unknown>) => buildRecordSchema.parse({ ok: true, id: "b1", name: "water", ...fields });
    const finished = "2026-10-26T14:09:00Z";

    const built = settle(card, record({ status: "done", version: "0.1.0", finished }));
    expect([built.state, built.steps.map((s) => s.state), built.note]).toEqual([
      "done",
      ["failed", "done", "done", "done"],
      `Finished at ${hhmm(finished)}: v0.1.0 is running.`,
    ]);
    expect(built.steps[1].since).toBeNull(); // no clock on a step that is over

    const failed = settle(card, record({ status: "failed", stage: "tests", error: "no working module after 6 rounds", finished }));
    expect([failed.state, failed.steps.map((s) => s.state), failed.note]).toEqual([
      "failed",
      ["failed", "failed", "pending", "pending"],
      `Stopped at ${hhmm(finished)} (tests): no working module after 6 rounds`,
    ]);

    expect(settle(card, record({ status: "building", stage: "verify" }))).toBe(card); // still going: as it is
    const over = { ...card, state: "done" as const };
    expect(settle(over, record({ status: "failed" }))).toBe(over); // a card that has its end keeps it
  });
});
