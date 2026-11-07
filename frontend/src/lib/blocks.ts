// The arithmetic of the blocks Main shows under a reply (components/ui/blocks): sorting a table, the ticks of an
// axis and what they read, where a point goes. Pure, so each piece is tested on its own. The values themselves
// are never formatted here: Main sent each one as it reads (`Cell.s`); only an axis tick, which no value is,
// is written by the app.

import type { BlockColumn, Cell } from "@/lib/schemas";

export type Sort = { col: number; dir: "asc" | "desc" } | null;

export const isNumeric = (c: BlockColumn) => c.format === "number" || c.format === "money" || c.format === "percent";

/** A cell's value as a number, or null (text, a missing value). */
export const num = (c: Cell | undefined): number | null => (typeof c?.v === "number" && Number.isFinite(c.v) ? c.v : null);

function compare(a: Cell | undefined, b: Cell | undefined): number {
  const [x, y] = [a?.v ?? null, b?.v ?? null];
  if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1; // a missing value sorts last either way
  if (typeof x === "number" && typeof y === "number") return x - y;
  return String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: "base" });
}

/** The rows in `sort`'s order (the data's own when null); a row with no value there goes last, either way. */
export function sortRows(rows: Cell[][], sort: Sort): Cell[][] {
  if (!sort) return rows;
  const sign = sort.dir === "asc" ? 1 : -1;
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      const [x, y] = [a.r[sort.col], b.r[sort.col]];
      const missing = (x?.v ?? null) === null || (y?.v ?? null) === null;
      return (missing ? compare(x, y) : sign * compare(x, y)) || a.i - b.i;
    })
    .map(({ r }) => r);
}

/** A header's next sort: numbers start with the largest, text and dates from the start; a third click clears. */
export function nextSort(sort: Sort, col: number, numeric: boolean): Sort {
  const first = numeric ? "desc" : "asc";
  if (!sort || sort.col !== col) return { col, dir: first };
  return sort.dir === first ? { col, dir: first === "asc" ? "desc" : "asc" } : null;
}

/** Round axis ticks from 0 (or below, for negatives) past the data's top: 1, 2 or 5 times a power of ten. */
export function niceTicks(lo: number, hi: number, count = 5): number[] {
  const min = Math.min(0, lo);
  const max = hi > min ? hi : min + 1;
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let t = start; t < max + step * 0.999; t += step) ticks.push(Number(t.toPrecision(12)));
  return ticks;
}

/** An axis tick, in the series' own units: in full under 10,000, compact above (12.5K, 1.2M). */
export function tickLabel(n: number, c: Pick<BlockColumn, "prefix" | "suffix">): string {
  const abs = Math.abs(n);
  const body = abs >= 1e6 ? `${trim(abs / 1e6)}M` : abs >= 1e4 ? `${trim(abs / 1e3)}K` : abs.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return `${n < 0 ? "-" : ""}${c.prefix}${body}${c.suffix}`;
}

const trim = (n: number) => String(Number(n.toFixed(1)));

/** Where each point sits along the x axis, 0..1: by time when every x is a date, else evenly in order. */
export function positions(xs: Cell[]): number[] {
  if (xs.length < 2) return xs.map(() => 0.5);
  const times = xs.map((c) => (typeof c.v === "string" ? Date.parse(c.v) : NaN));
  if (times.every(Number.isFinite)) {
    const [a, b] = [Math.min(...times), Math.max(...times)];
    if (b > a) return times.map((t) => (t - a) / (b - a));
  }
  return xs.map((_, i) => i / (xs.length - 1));
}

/** Of `positions`, the one nearest `at` (0..1). */
export function nearest(pos: number[], at: number): number {
  let best = 0;
  pos.forEach((p, i) => {
    if (Math.abs(p - at) < Math.abs(pos[best] - at)) best = i;
  });
  return best;
}

/** At most `n` of `count` indexes, one every few at an even step, the first and the last always in: the x labels
 *  a line has room for. The last replaces its neighbour when the two would crowd. */
export function spread(count: number, n: number): number[] {
  if (count <= n) return Array.from({ length: count }, (_, i) => i);
  const step = Math.ceil((count - 1) / Math.max(1, n - 1));
  const out: number[] = [];
  for (let i = 0; i < count; i += step) out.push(i);
  if (out[out.length - 1] !== count - 1) {
    if (count - 1 - out[out.length - 1] < step / 2) out.pop();
    out.push(count - 1);
  }
  return out;
}

/** A series' colour: moss when it is alone (the title names it), else the chart palette in its fixed order. */
export function seriesColor(i: number, count: number): string {
  return count === 1 ? "var(--color-moss)" : `var(--color-series-${i + 1})`;
}
