import { describe, expect, it } from "vitest";
import { applyStream, dropStreams, type StreamText } from "@/lib/bus";
import type { BusEvent, StreamDelta } from "@/lib/schemas";

const delta = (over: Partial<StreamDelta>): StreamDelta => ({
  cause: "m1",
  request: "r1",
  slot: "planner",
  provider: "claude",
  seq: 1,
  text: "",
  thinking: "",
  done: false,
  ...over,
});

describe("a reply being written", () => {
  it("accumulates the pieces of one model call, keyed by the message it answers", () => {
    let s: Record<string, StreamText> = {};
    s = applyStream(s, delta({ seq: 1, text: "Hel" }));
    s = applyStream(s, delta({ seq: 2, text: "lo" }));
    s = applyStream(s, delta({ cause: "m2", request: "r9", seq: 1, text: "other" }));
    expect(s.m1).toEqual({ request: "r1", provider: "claude", text: "Hello", thinking: "", done: false });
    expect(s.m2.text).toBe("other");
    s = applyStream(s, delta({ seq: 3, text: "", done: true }));
    expect(s.m1).toMatchObject({ text: "Hello", done: true });
  });

  it("keeps the thinking apart from the text, both growing with each frame", () => {
    let s = applyStream({}, delta({ seq: 1, thinking: "The user " }));
    s = applyStream(s, delta({ seq: 2, thinking: "says hi." }));
    expect(s.m1).toMatchObject({ thinking: "The user says hi.", text: "" });
    s = applyStream(s, delta({ seq: 3, text: "Hi!" }));
    expect(s.m1).toMatchObject({ thinking: "The user says hi.", text: "Hi!" });
  });

  it("starts over when the next planner round begins: a round that ended in tool calls is not the reply", () => {
    let s = applyStream({}, delta({ request: "r1", thinking: "Save the name first.", text: "Let me check…" }));
    s = applyStream(s, delta({ request: "r2", seq: 1, text: "hello is running." }));
    expect(s.m1).toMatchObject({ request: "r2", text: "hello is running.", thinking: "" });
  });

  it("is dropped once the reply itself lands, and untouched otherwise", () => {
    const s = applyStream({}, delta({ text: "Hello" }));
    const say: BusEvent = { seq: 9, subject: "out.say", data: { id: "a1", cause: "m1", text: "Hello" }, received: "t" };
    const other: BusEvent = { seq: 10, subject: "trace.plan", data: { id: "t1", cause: "m1" }, received: "t" };
    expect(dropStreams(s, [other])).toBe(s);
    expect(dropStreams(s, [say])).toEqual({});
  });
});
