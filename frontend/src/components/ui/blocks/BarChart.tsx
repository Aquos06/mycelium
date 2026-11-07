"use client";

// Amounts by a name (largest first, as Main ranked them) or by a day, as horizontal bars from one baseline: thin
// (never past 24px), square at the baseline and rounded at the data end, the value at the tip in text ink. Every
// value is printed, so no tooltip hides one. Two to four series stack their bars per row, in the legend's order.

import type { CSSProperties } from "react";
import { num, seriesColor } from "@/lib/blocks";
import type { ChartBlock } from "@/lib/schemas";

const LABEL_ROOM = "6.5rem"; // what the value at a bar's tip needs beside the longest bar

export function BarChart({ block }: { block: ChartBlock }) {
  const top = Math.max(0, ...block.points.flatMap((p) => p.y.map((c) => num(c) ?? 0))) || 1;
  const many = block.series.length > 1;
  // one label column for every row, as wide as the longest name (up to 40%), so the bars share their baseline
  const longest = Math.max(4, ...block.points.map((p) => p.x.s.length));
  const style = { "--label": `${Math.min(20, longest) + 1}ch` } as CSSProperties;
  return (
    <ul
      className="m-0 flex list-none flex-col gap-2.5 px-4 py-3"
      style={style}
      aria-label={block.title || `${block.series.map((s) => s.label).join(", ")} by ${block.x.label}`}
    >
      {block.points.map((p, pi) => (
        <li key={pi} className="grid grid-cols-[min(var(--label),40%)_1fr] items-center gap-3 text-[13px]">
          <span className="truncate text-ink2" title={p.x.s}>
            {p.x.s}
          </span>
          <span className="flex min-w-0 flex-col gap-0.5">
            {block.series.map((s, si) => {
              const v = Math.max(0, num(p.y[si]) ?? 0);
              return (
                <span key={s.key + si} className="flex min-w-0 items-center gap-2">
                  <span
                    className="shrink-0 rounded-r-[4px]"
                    style={{
                      width: v ? `max(2px, calc(${v / top} * (100% - ${LABEL_ROOM})))` : 0,
                      height: many ? 8 : 14,
                      background: seriesColor(si, block.series.length),
                    }}
                    aria-hidden="true"
                  />
                  <span className="shrink-0 text-[12.5px] whitespace-nowrap tabular-nums text-ink1">
                    {many && <span className="sr-only">{s.label}: </span>}
                    {p.y[si]?.s ?? "—"}
                  </span>
                </span>
              );
            })}
          </span>
        </li>
      ))}
    </ul>
  );
}
