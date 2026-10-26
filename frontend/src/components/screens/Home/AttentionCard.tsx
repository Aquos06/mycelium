"use client";

// One thing that needs you: a question Main asked, a notification, a key that is missing.

import type { CSSProperties, ReactNode } from "react";
import { DOMAIN, domainOf } from "@/lib/domains";
import { hhmm } from "@/lib/format";

export function AttentionCard({
  subject,
  glyph,
  title,
  body,
  at,
  children,
}: {
  subject: string;
  glyph: string;
  title: string;
  body: string;
  at?: string;
  children?: ReactNode;
}) {
  const d = DOMAIN[domainOf(subject)];
  return (
    <div className="flex flex-col gap-3 rounded-[14px] border border-line bg-surface p-4" role="group" aria-label={title}>
      <div className="flex items-center gap-2.5">
        <span
          className="flex size-7 items-center justify-center rounded-lg bg-[var(--glyph-soft)] font-mono text-[13px] font-medium text-[var(--glyph-c)]"
          style={{ "--glyph-c": d.c, "--glyph-soft": d.soft } as CSSProperties}
        >
          {glyph}
        </span>
        <span className="font-mono text-[11.5px]" style={{ color: d.c }}>
          {subject}
        </span>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-[3px]">
        <span className="text-[14.5px] leading-[1.35] font-medium text-pretty">{title}</span>
        <span className="text-[13px] leading-[1.45] text-pretty text-ink2">
          {body}
          {at ? ` · ${hhmm(at)}` : ""}
        </span>
      </div>
      {children}
    </div>
  );
}
