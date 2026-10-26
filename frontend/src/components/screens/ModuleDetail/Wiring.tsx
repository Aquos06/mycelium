"use client";

// What comes in on the left, the module in the middle, what goes out on the right.

import type { StatusKind } from "@/lib/schemas";
import { Chip, StatusDot } from "@/components/ui/Primitives";

export function Wiring({ name, kind, listens, emits, answers }: { name: string; kind: StatusKind; listens: string[]; emits: string[]; answers: string[] }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-4 rounded-card border border-line bg-paper p-6" aria-label="Wiring">
      <div className="flex flex-col items-end gap-1.5">
        <span className="text-[11.5px] text-ink3">listens</span>
        {listens.length === 0 && <span className="text-[12px] text-ink3">—</span>}
        {listens.map((w) => (
          <Chip key={w} subject={w.startsWith("rpc") ? "rpc" : w} text={w} lg />
        ))}
      </div>
      <div className="flex items-center gap-2.5">
        <span className="h-px w-7 bg-ink4" />
        <div className="flex items-center gap-2 rounded-card border border-line-strong bg-surface px-[18px] py-3.5 font-mono text-[14px] font-medium shadow-node">
          <StatusDot kind={kind} />
          {name}
        </div>
        <span className="h-px w-7 bg-ink4" />
      </div>
      <div className="flex flex-col items-start gap-1.5">
        <span className="text-[11.5px] text-ink3">emits · answers</span>
        {emits.length === 0 && answers.length === 0 && <span className="text-[12px] text-ink3">—</span>}
        {emits.map((w) => (
          <Chip key={w} subject={w} lg />
        ))}
        {answers.map((w) => (
          <Chip key={w} subject="rpc" text={`rpc · ${w}`} lg />
        ))}
      </div>
    </div>
  );
}
