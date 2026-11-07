"use client";

// The card every block sits in: its title, a control or two on the right, then the block. A container, so a block
// lays itself out by the room it has (a table becomes cards in a narrow chat), not by the window.

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Frame({ kind, title, actions, footer, children }: { kind: string; title: string; actions?: ReactNode; footer?: ReactNode; children: ReactNode }) {
  return (
    <figure className="@container m-0 min-w-0 overflow-hidden rounded-card border border-line bg-surface" data-kind={`block-${kind}`}>
      {(title || actions) && (
        <figcaption className={cn("flex min-h-10 items-center gap-3 border-b border-sunken px-4 py-2", title ? "justify-between" : "justify-end")}>
          {title && <span className="min-w-0 truncate text-[13.5px] font-medium text-ink">{title}</span>}
          {actions}
        </figcaption>
      )}
      {children}
      {footer && <div className="border-t border-sunken px-4 py-2 text-[12.5px] text-ink3">{footer}</div>}
    </figure>
  );
}
