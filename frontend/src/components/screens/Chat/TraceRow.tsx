"use client";

// The plan under a reply: what Main used, how many rounds, what it cost, how long, or why it failed.

import { usd } from "@/lib/format";
import type { PlanTrace } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import { Chip } from "@/components/ui/Primitives";

export function TraceRow({ t }: { t: PlanTrace }) {
  const tools = t.tools.map((x) => x.name);
  const label = t.error ? "Could not answer" : tools.length ? `Planned with ${tools.join(", ")}` : "Planned";
  const pack = t.pack?.items?.length ?? 0;
  const meta = [
    `${t.rounds} ${t.rounds === 1 ? "round" : "rounds"}`,
    pack ? `${pack} ${pack === 1 ? "note" : "notes"} recalled` : null,
    t.cost_usd ? usd(t.cost_usd, 4) : "free",
    `${t.latency_ms} ms`,
    t.error ? t.error : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="-my-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-ink3 md:ml-[38px]" data-kind="trace">
      <span className={cn("size-1.5 rounded-[2px]", t.error ? "bg-red" : "bg-brain")} />
      <span>{label}</span>
      <Chip subject="trace.plan" />
      <span className="text-ink4" title={meta}>
        {meta}
      </span>
    </div>
  );
}
