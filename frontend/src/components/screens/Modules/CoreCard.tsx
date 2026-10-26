"use client";

// One core service: the same card as a module, with a probe instead of a sparkline.

import Link from "next/link";
import type { CoreService } from "@/lib/core";
import { ROUTES } from "@/lib/nav";
import type { StatusKind } from "@/lib/schemas";
import { Chip, Pill } from "@/components/ui/Primitives";

export function CoreCard({
  c,
  status,
  metric,
  metricLabel,
}: {
  c: CoreService;
  status: { kind: StatusKind; label: string };
  metric: string;
  metricLabel: string;
}) {
  return (
    <Link
      href={ROUTES.module(c.name)}
      data-module={c.name}
      className="flex w-full flex-col gap-3 rounded-card border border-line bg-surface p-4 text-left text-ink no-underline hover:shadow-lift"
    >
      <div className="flex items-center gap-2.5">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-sunken font-mono text-[14px] font-medium text-ink2">{c.name[0]}</div>
        <div className="flex flex-col leading-[1.25]">
          <span className="font-mono text-[14px] font-medium">{c.name}</span>
          <span className="text-[12px] text-ink3">core service</span>
        </div>
        <span className="ml-auto">
          <Pill kind={status.kind} label={status.label} />
        </span>
      </div>
      <span className="text-[13px] text-pretty text-ink2">{c.purpose}</span>
      <div className="flex flex-wrap gap-[5px]">
        {c.listens.slice(0, 3).map((w) => (
          <Chip key={w} subject={w.startsWith("rpc") ? "rpc" : w} text={w} />
        ))}
        {c.emits.slice(0, 3).map((w) => (
          <Chip key={w} subject={w} />
        ))}
      </div>
      <div className="flex items-end justify-between border-t border-sunken pt-3">
        <div className="flex flex-col">
          <span className="text-[18px] leading-[1.2] font-semibold tracking-[-0.02em]">{metric}</span>
          <span className="text-[12px] text-ink3">{metricLabel}</span>
        </div>
      </div>
    </Link>
  );
}
