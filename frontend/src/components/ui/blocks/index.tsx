"use client";

// What Main shows under a reply (out.say / out.ask `blocks`): a module's data as a table, a chart, stats, details
// or a meter, each in its own card, in the order Main sent them. Values arrive formatted (lib/schemas: Cell), so
// nothing here decides how a number reads; it only lays the numbers out.

import type { Block } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import { Chart } from "./Chart";
import { Details, Meter, Stats } from "./Figures";
import { Frame } from "./Frame";
import { TableBody } from "./TableBody";

export function Blocks({ blocks, className }: { blocks: Block[] | undefined; className?: string }) {
  if (!blocks?.length) return null;
  return (
    <div className={cn("flex min-w-0 flex-col gap-3", className)}>
      {blocks.map((b, i) => (
        <OneBlock key={i} block={b} />
      ))}
    </div>
  );
}

function OneBlock({ block }: { block: Block }) {
  switch (block.kind) {
    case "table": {
      const footer = block.total > block.rows.length ? `The first ${block.rows.length} of ${block.total}` : undefined;
      return (
        <Frame kind="table" title={block.title} footer={footer}>
          <TableBody label={block.title || "Table"} columns={block.columns} rows={block.rows} />
        </Frame>
      );
    }
    case "chart":
      return <Chart block={block} />;
    case "stats":
      return <Stats block={block} />;
    case "details":
      return <Details block={block} />;
    case "meter":
      return <Meter block={block} />;
  }
}
