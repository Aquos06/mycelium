"use client";

// One grown module: who it is, what it is wired to, how alive it has been.

import Link from "next/link";
import { ROUTES } from "@/lib/nav";
import type { ModuleHealth, ModuleRow } from "@/lib/schemas";
import { statusOf } from "@/lib/status";
import { cn } from "@/lib/utils";
import { Chip, Pill, Spark } from "@/components/ui/Primitives";

export function ModuleCard({ m, count, spark, health }: { m: ModuleRow; count: number; spark: number[]; health?: ModuleHealth }) {
  const kind = statusOf(m);
  const unhealthy = kind === "running" && health && !health.ok;
  const man = m.manifest;
  return (
    <Link
      href={ROUTES.module(m.name)}
      data-module={m.name}
      className={cn(
        "flex w-full flex-col gap-3 rounded-card border border-line bg-surface p-4 text-left text-ink no-underline hover:shadow-lift",
        kind === "seed" && "border-dashed border-line-strong bg-paper",
      )}
    >
      <div className="flex items-center gap-2.5">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-sunken font-mono text-[14px] font-medium text-ink2">{m.name[0]}</div>
        <div className="flex flex-col leading-[1.25]">
          <span className="font-mono text-[14px] font-medium">{m.name}</span>
          <span className="text-[12px] text-ink3">v{m.version}</span>
        </div>
        <span className="ml-auto">{unhealthy ? <Pill kind="failed" label="Unhealthy" /> : <Pill kind={kind} />}</span>
      </div>
      <span className="text-[13px] text-pretty text-ink2">{man.purpose}</span>
      <div className="flex flex-wrap gap-[5px]">
        {man.subscribes.map((w) => (
          <Chip key={`s-${w}`} subject={w} />
        ))}
        {man.emits.map((w) => (
          <Chip key={`e-${w}`} subject={`mod.${m.name}.${w}`} />
        ))}
        {man.requests.map((w) => (
          <Chip key={`r-${w}`} subject="rpc" text={`rpc · ${w}`} />
        ))}
      </div>
      <div className="flex items-end justify-between border-t border-sunken pt-3">
        <div className="flex flex-col">
          <span className="text-[18px] leading-[1.2] font-semibold tracking-[-0.02em]">{count}</span>
          <span className="text-[12px] text-ink3">{count === 1 ? "event seen" : "events seen"}</span>
        </div>
        <Spark values={spark} />
      </div>
    </Link>
  );
}
