"use client";

// The blocks that are figures, not plots: stats (a few headline numbers in tiles), details (one record, every
// field labelled) and a meter (one number against a goal). A big figure keeps proportional digits; tabular ones
// are for columns.

import { num } from "@/lib/blocks";
import type { DetailsBlock, MeterBlock, StatsBlock } from "@/lib/schemas";
import { Frame } from "./Frame";

export function Stats({ block }: { block: StatsBlock }) {
  return (
    <Frame kind="stats" title={block.title}>
      <div className="overflow-hidden">
        <dl className="m-0 -mr-px -mb-px flex flex-wrap">
          {block.stats.map((f, i) => (
            <div key={i} className="flex min-w-0 flex-[1_1_8.5rem] flex-col gap-0.5 border-r border-b border-line px-4 py-3">
              <dt className="text-[12.5px] text-ink3">{f.label}</dt>
              <dd className="m-0 text-[22px] leading-tight font-semibold wrap-break-word text-ink">{f.value.s}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Frame>
  );
}

export function Details({ block }: { block: DetailsBlock }) {
  return (
    <Frame kind="details" title={block.title}>
      <dl className="m-0 grid grid-cols-[minmax(0,max-content)_1fr] gap-x-6 gap-y-1.5 px-4 py-3 text-[13.5px]">
        {block.items.map((f, i) => (
          <div key={i} className="contents">
            <dt className="text-ink3">{f.label}</dt>
            <dd className="m-0 wrap-break-word text-ink1">{f.value.s}</dd>
          </div>
        ))}
      </dl>
    </Frame>
  );
}

export function Meter({ block }: { block: MeterBlock }) {
  const [value, max] = [num(block.value) ?? 0, num(block.max) ?? 0];
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <Frame kind="meter" title={block.title}>
      <div className="px-4 py-3">
        <div className="flex items-baseline justify-between gap-3 text-[13.5px]">
          <span className="font-medium text-ink">{block.label}</span>
          <span className="tabular-nums text-ink2">
            {block.value.s} / {block.max.s} · {pct}%
          </span>
        </div>
        <div
          role="meter"
          aria-label={block.label}
          aria-valuemin={0}
          aria-valuemax={max}
          aria-valuenow={value}
          aria-valuetext={`${block.value.s} of ${block.max.s}, ${pct}%`}
          className="mt-2 h-2 overflow-hidden rounded-full bg-moss-soft"
        >
          <div className="h-full rounded-full bg-moss" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
        </div>
      </div>
    </Frame>
  );
}
