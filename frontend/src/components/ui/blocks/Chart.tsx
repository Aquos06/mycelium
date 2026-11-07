"use client";

// A chart block: bars for amounts by a name, a line or an area over time. Two or more series get a legend (their
// colours are the chart palette, in a fixed order). Every chart has its table view, one click away: the same
// points as rows, for a value no label shows and for anyone the colours do not reach.

import { Table2 } from "lucide-react";
import { useState } from "react";
import { seriesColor } from "@/lib/blocks";
import type { ChartBlock } from "@/lib/schemas";
import { BarChart } from "./BarChart";
import { Frame } from "./Frame";
import { LineChart } from "./LineChart";
import { TableBody } from "./TableBody";

export function Chart({ block }: { block: ChartBlock }) {
  const [asTable, setAsTable] = useState(false);
  const shown = block.points.length;
  const footer =
    block.total > shown ? (block.chart === "bar" ? `The largest ${shown} of ${block.total}` : `The latest ${shown} of ${block.total}`) : undefined;
  const toggle = (
    <button
      type="button"
      aria-pressed={asTable}
      onClick={() => setAsTable(!asTable)}
      className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-row px-2 text-[12.5px] text-ink3 hover:bg-hover hover:text-ink aria-pressed:bg-sunken aria-pressed:text-ink"
    >
      <Table2 className="size-3.5" aria-hidden="true" />
      Table
    </button>
  );
  return (
    <Frame kind="chart" title={block.title} actions={toggle} footer={footer}>
      {block.series.length > 1 && !asTable && (
        <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 px-4 pt-3 text-[12.5px] text-ink2" aria-label="Legend">
          {block.series.map((s, i) => (
            <li key={s.key + i} className="flex items-center gap-1.5">
              <span className={block.chart === "bar" ? "size-2.5 rounded-[3px]" : "h-0.5 w-3 rounded-full"} style={{ background: seriesColor(i, block.series.length) }} />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      {asTable ? (
        <TableBody label={block.title || "Chart data"} columns={[block.x, ...block.series]} rows={block.points.map((p) => [p.x, ...p.y])} />
      ) : block.chart === "bar" ? (
        <BarChart block={block} />
      ) : (
        <LineChart block={block} />
      )}
    </Frame>
  );
}
