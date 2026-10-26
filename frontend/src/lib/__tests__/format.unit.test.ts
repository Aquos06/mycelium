import { describe, expect, it } from "vitest";
import { ago, compact, dayPart, greeting, groupOf, hhmm, initials, plural, sparkline, usd } from "@/lib/format";

const T = new Date("2026-10-26T14:30:00");

describe("format", () => {
  it("hhmm reads the local clock and tolerates garbage", () => {
    expect(hhmm(T.toISOString())).toBe("14:30");
    expect(hhmm("nope")).toBe("");
  });

  it("ago says now, minutes, hours, then the clock", () => {
    const now = T.getTime();
    expect(ago(new Date(now - 10_000).toISOString(), now)).toBe("now");
    expect(ago(new Date(now - 120_000).toISOString(), now)).toBe("2m");
    expect(ago(new Date(now - 3 * 3600_000).toISOString(), now)).toBe("3h");
    expect(ago(new Date(now - 8 * 3600_000).toISOString(), now)).toBe("06:30");
  });

  it("groupOf buckets a day the way the timeline reads it", () => {
    const at = (h: number, m = 0) => new Date(2026, 9, 26, h, m).toISOString();
    expect(groupOf(at(14, 25), T)).toBe("Just now");
    expect(groupOf(at(9), T)).toBe("This morning");
    expect(groupOf(at(13), T)).toBe("This afternoon");
    expect(groupOf(new Date(2026, 9, 25, 20).toISOString(), T)).toBe("Yesterday");
    expect(groupOf(new Date(2026, 9, 20, 20).toISOString(), T)).toBe("Earlier");
    expect(groupOf("nope", T)).toBe("Earlier");
  });

  it("greets by the part of the day", () => {
    expect(dayPart(new Date(2026, 0, 1, 3))).toBe("night");
    expect(greeting("Hansen", new Date(2026, 0, 1, 9))).toBe("Good morning, Hansen");
    expect(greeting("Hansen", new Date(2026, 0, 1, 20))).toBe("Good evening, Hansen");
  });

  it("formats money, counts and plurals", () => {
    expect(usd(1.5)).toBe("$1.50");
    expect(usd(null)).toBe("—");
    expect(usd(0.00312, 4)).toBe("$0.0031");
    expect(compact(999)).toBe("999");
    expect(compact(12_345)).toBe("12.3k");
    expect(plural(1, "module")).toBe("1 module");
    expect(plural(2, "module")).toBe("2 modules");
    expect(plural(0, "reply", "replies")).toBe("0 replies");
    expect(initials("hansen")).toBe("H");
    expect(initials("  ")).toBe("?");
  });

  it("sparkline buckets the last hours and keeps zero at zero", () => {
    const now = T.getTime();
    const stamps = [now - 10_000, now - 20_000, now - 3600_000 * 2.5].map((t) => new Date(t).toISOString());
    const bars = sparkline(stamps, 7, now);
    expect(bars).toHaveLength(7);
    expect(bars[6]).toBe(100); // two in the last hour
    expect(bars[4]).toBe(50); // one, two and a half hours ago
    expect(bars.slice(0, 4).every((b) => b === 0)).toBe(true);
    expect(sparkline([], 7, now)).toEqual([0, 0, 0, 0, 0, 0, 0]);
  });
});
