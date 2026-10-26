import { describe, expect, it } from "vitest";
import { statusOf } from "@/lib/status";
import { ROUTES, tabForPath, threadOf } from "@/lib/nav";
import { mergeEvents, MAX_EVENTS } from "@/lib/bus";

describe("statusOf reads the registry and docker together", () => {
  it.each([
    ["running", "running", "running"],
    ["running", "exited", "failed"],
    ["running", null, "running"],
    ["building", null, "growing"],
    ["deploying", null, "growing"],
    ["failed", null, "failed"],
    ["stopped", null, "paused"],
    ["registered", "exited", "paused"],
    ["odd", null, "unknown"],
    ["", null, "seed"],
  ])("%s + %s → %s", (status, container, kind) => {
    expect(statusOf({ status, container })).toBe(kind);
  });
});

describe("nav", () => {
  it("names every route in one place", () => {
    expect(ROUTES.chat("a b")).toBe("/chat/a%20b");
    expect(ROUTES.module("hello")).toBe("/modules/hello");
    expect(ROUTES.settings()).toBe("/settings/models");
  });
  it("finds the tab and the thread in a path", () => {
    expect(tabForPath("/")).toBe("home");
    expect(tabForPath("/modules/hello")).toBe("modules");
    expect(tabForPath("/voice")).toBeNull();
    expect(threadOf("/chat/web-abc")).toBe("web-abc");
    expect(threadOf("/modules")).toBe("web");
  });
});

describe("mergeEvents", () => {
  const e = (seq: number, received: string) => ({ seq, subject: "x", data: {}, received });
  it("dedupes by (received, seq), sorts oldest first and caps the list", () => {
    const out = mergeEvents([e(1, "2026-01-01T00:00:01Z")], [e(1, "2026-01-01T00:00:01Z"), e(2, "2026-01-01T00:00:00Z")]);
    expect(out.map((x) => x.seq)).toEqual([2, 1]);
    const many = Array.from({ length: MAX_EVENTS + 5 }, (_, i) => e(i, `2026-01-01T00:00:${String(i % 60).padStart(2, "0")}Z`));
    expect(mergeEvents([], many)).toHaveLength(MAX_EVENTS);
  });
  it("returns the same array when nothing came in", () => {
    const prev = [e(1, "2026-01-01T00:00:01Z")];
    expect(mergeEvents(prev, [])).toBe(prev);
  });
});
