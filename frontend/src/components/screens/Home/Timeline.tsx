"use client";

// The bus as a list you can read: grouped by when, one plain sentence per event, the subject's hue as a
// mark. The machine's side (subject, payload, numbers) only in raw mode.

import { useMemo } from "react";
import { DOMAIN, domainOf, read } from "@/lib/domains";
import { groupOf, hhmm } from "@/lib/format";
import type { BusEvent } from "@/lib/schemas";
import { cn } from "@/lib/utils";

export function Timeline({ events, raw, now }: { events: BusEvent[]; raw: boolean; now: number }) {
  const groups = useMemo(() => {
    const out: { label: string; items: BusEvent[] }[] = [];
    for (const e of events) {
      const label = groupOf(e.received, new Date(now));
      const last = out[out.length - 1];
      if (last && last.label === label) last.items.push(e);
      else out.push({ label, items: [e] });
    }
    return out;
  }, [events, now]);

  return (
    <ol className="m-0 flex list-none flex-col p-0" aria-label="Timeline">
      {groups.map((g) => (
        <li key={g.label} className="flex flex-col">
          <span className="pt-1.5 pb-1 text-[12px] text-ink3 md:pl-16">{g.label}</span>
          {g.items.map((e) => {
            const r = read(e, raw);
            const fresh = now - new Date(e.received).getTime() < 60_000;
            return (
              <div
                key={`${e.received}|${e.seq}`}
                data-subject={e.subject}
                className={cn("grid grid-cols-[52px_12px_minmax(0,1fr)] items-start gap-x-3 rounded-lg py-[7px]", fresh && "animate-row-in")}
              >
                <span className="pt-0.5 text-right font-mono text-[11.5px] text-ink3">{fresh ? "now" : hhmm(e.received)}</span>
                <span className="mt-1.5 size-2 justify-self-center rounded-full" style={{ background: DOMAIN[domainOf(e.subject)].c }} />
                <span className="flex min-w-0 flex-col">
                  <span className="text-[14px] leading-[1.4] wrap-break-word text-pretty text-ink" title={raw ? undefined : r.meta}>
                    {r.text}
                  </span>
                  {raw && (
                    <span className="truncate font-mono text-[11.5px] text-ink3" title={r.meta}>
                      {r.meta}
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </li>
      ))}
    </ol>
  );
}
