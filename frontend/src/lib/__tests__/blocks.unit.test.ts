import { describe, expect, it } from "vitest";
import { nearest, nextSort, niceTicks, positions, seriesColor, sortRows, spread, tickLabel } from "@/lib/blocks";
import { blocksSchema, moduleViewsSchema, saySchema, type Cell } from "@/lib/schemas";

const n = (v: number | null): Cell => ({ v, s: v === null ? "—" : `NT$${v}` });
const t = (v: string): Cell => ({ v, s: v });

describe("the blocks' arithmetic", () => {
  it("sorts numbers by their value, text naturally, and a missing value last either way", () => {
    const rows = [[t("b"), n(85)], [t("a10"), n(1200)], [t("a9"), n(null)], [t("c"), n(350)]];
    expect(sortRows(rows, { col: 1, dir: "desc" }).map((r) => r[1].v)).toEqual([1200, 350, 85, null]);
    expect(sortRows(rows, { col: 1, dir: "asc" }).map((r) => r[1].v)).toEqual([85, 350, 1200, null]);
    expect(sortRows(rows, { col: 0, dir: "asc" }).map((r) => r[0].v)).toEqual(["a9", "a10", "b", "c"]);
    expect(sortRows(rows, null)).toBe(rows); // the data's own order
  });

  it("a header starts numbers with the largest, text from the start, and a third click clears", () => {
    expect([nextSort(null, 1, true), nextSort({ col: 1, dir: "desc" }, 1, true), nextSort({ col: 1, dir: "asc" }, 1, true)]).toEqual([
      { col: 1, dir: "desc" },
      { col: 1, dir: "asc" },
      null,
    ]);
    expect(nextSort({ col: 1, dir: "desc" }, 0, false)).toEqual({ col: 0, dir: "asc" });
  });

  it("an axis runs from zero past the top in round steps", () => {
    expect(niceTicks(900, 2100)).toEqual([0, 500, 1000, 1500, 2000, 2500]);
    expect(niceTicks(0, 3420)).toEqual([0, 1000, 2000, 3000, 4000]);
    expect(niceTicks(-120, 300)).toEqual([-200, -100, 0, 100, 200, 300]);
    expect(niceTicks(0, 0)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]); // nothing but zero: an axis all the same
  });

  it("a tick reads in the series' units, in full under 10,000 and compact above", () => {
    const money = { prefix: "NT$", suffix: "" };
    expect([2000, 12500, 1_200_000, -500].map((v) => tickLabel(v, money))).toEqual(["NT$2,000", "NT$12.5K", "NT$1.2M", "-NT$500"]);
    expect(tickLabel(75, { prefix: "", suffix: "%" })).toBe("75%");
  });

  it("dates sit by time, anything else evenly; the pointer finds the nearest", () => {
    expect(positions([t("2026-11-01"), t("2026-11-02"), t("2026-11-05")])).toEqual([0, 0.25, 1]);
    expect(positions([t("food"), t("coffee"), t("rent")])).toEqual([0, 0.5, 1]);
    expect(positions([t("only")])).toEqual([0.5]);
    expect(nearest([0, 0.25, 1], 0.6)).toBe(1);
  });

  it("x labels go at an even step, with the first and the last", () => {
    expect(spread(3, 6)).toEqual([0, 1, 2]);
    expect(spread(7, 6)).toEqual([0, 2, 4, 6]);
    expect(spread(30, 6)).toEqual([0, 6, 12, 18, 24, 29]);
    expect(spread(26, 6)).toEqual([0, 5, 10, 15, 20, 25]);
  });

  it("a series alone is moss; two or more take the chart palette in order", () => {
    expect(seriesColor(0, 1)).toBe("var(--color-moss)");
    expect([0, 1].map((i) => seriesColor(i, 2))).toEqual(["var(--color-series-1)", "var(--color-series-2)"]);
  });
});

describe("a reply's blocks", () => {
  it("are read one by one: a kind this app does not know is left out, never the reply", () => {
    const stats = { kind: "stats", stats: [{ label: "Total", value: { v: 3420, s: "NT$3,420" } }] };
    expect(blocksSchema.parse([{ kind: "map", pins: [] }, stats, { kind: "table" }])).toEqual([{ ...stats, title: "", text: "" }]);
    const say = saySchema.parse({ id: "a1", channel: "web", thread: "web", text: "hi" });
    expect(say.blocks).toEqual([]);
  });

  it("a module page's view this app cannot read says so, and the others still show", () => {
    const page = moduleViewsSchema.parse({
      name: "spending",
      running: true,
      declared: true,
      views: [
        { id: "map", title: "Where", request: "places", block: { kind: "map", pins: [] } },
        { id: "week", title: "This week", request: "summary", block: { kind: "stats", stats: [{ label: "Total", value: { v: 1, s: "1" } }] } },
        { id: "slow", title: "Slow", request: "history", block: null, error: "spending.history did not answer (TimeoutError)" },
      ],
    });
    expect(page.views.map((v) => [v.id, v.block?.kind ?? null, v.error])).toEqual([
      ["map", null, "this app cannot show this kind of view yet"],
      ["week", "stats", null],
      ["slow", null, "spending.history did not answer (TimeoutError)"],
    ]);
  });
});
