"use client";

// The small shared pieces: status pills, subject chips, sparklines, dots, labels, cards, notes.

import { Info } from "lucide-react";
import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import { DOMAIN, domainOf } from "@/lib/domains";
import type { StatusKind } from "@/lib/schemas";
import { STATUS_LABEL } from "@/lib/status";
import { cn } from "@/lib/utils";

const PILL: Record<StatusKind, string> = {
  running: "bg-moss-soft text-moss",
  growing: "bg-amber-soft text-amber-text [--pill-dot:var(--color-amber)]",
  failed: "bg-red-soft text-red-text [--pill-dot:var(--color-red)]",
  paused: "bg-sunken text-ink2 [--pill-dot:var(--color-ink3)]",
  seed: "border border-dashed border-ink4 text-ink2",
  unknown: "bg-sunken text-ink3 [--pill-dot:var(--color-ink4)]",
};

export function Pill({ kind, label }: { kind: StatusKind; label?: string }) {
  return (
    <span className={cn("inline-flex h-[22px] items-center gap-1.5 rounded-[11px] px-2 text-[12px] font-medium whitespace-nowrap", PILL[kind])}>
      <span
        className={cn("size-1.5 shrink-0 rounded-full bg-[var(--pill-dot,currentColor)]", kind === "seed" && "border-[1.5px] border-ink3 bg-transparent")}
      />
      {label ?? STATUS_LABEL[kind]}
    </span>
  );
}

/** The dot colour a status wears outside a pill (the sidebar, the wiring node). */
export const STATUS_DOT: Record<StatusKind, string> = {
  running: "bg-moss",
  growing: "bg-amber",
  failed: "bg-red",
  paused: "bg-ink3",
  seed: "border-[1.5px] border-ink3 bg-transparent",
  unknown: "bg-ink4",
};

export function StatusDot({ kind, className }: { kind: StatusKind; className?: string }) {
  return <span className={cn("size-[7px] shrink-0 rounded-full", STATUS_DOT[kind], className)} />;
}

/** A subject, in its domain's hue. */
export function Chip({ subject, text, lg = false, className }: { subject: string; text?: string; lg?: boolean; className?: string }) {
  const d = DOMAIN[domainOf(subject)];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[5px] bg-[var(--chip-soft)] px-[7px] py-px font-mono text-[11.5px] whitespace-nowrap text-[var(--chip-c)]",
        lg && "rounded-md px-2 py-[3px] text-[12px]",
        className,
      )}
      style={{ "--chip-c": d.c, "--chip-soft": d.soft } as CSSProperties}
    >
      {text ?? subject}
    </span>
  );
}

/** A dot in the subject's hue: the timeline's mark, the event list's square. */
export function Mark({ subject, square = false, size = 8, className }: { subject: string; square?: boolean; size?: number; className?: string }) {
  const d = DOMAIN[domainOf(subject)];
  return (
    <span
      className={cn("inline-block shrink-0", square ? "rounded-[2px]" : "rounded-full", className)}
      style={{ width: size, height: size, background: d.c }}
    />
  );
}

export function Spark({ values, hot = true, small = false }: { values: number[]; hot?: boolean; small?: boolean }) {
  const last = values.length - 1;
  return (
    <span className={cn("flex items-end", small ? "h-5 gap-0.5" : "h-6 gap-[3px]")} aria-hidden="true">
      {values.map((v, i) => (
        <span
          key={i}
          className={cn("min-h-0.5 rounded-[1px] bg-moss-spark", small ? "w-[3px]" : "w-1", hot && i === last && v > 0 && "bg-moss")}
          style={{ height: `${Math.max(8, v)}%` }}
        />
      ))}
    </span>
  );
}

export function Spinner({ ink = false, className }: { ink?: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "inline-block size-[11px] shrink-0 animate-spin-fast rounded-full border-[1.5px]",
        ink ? "border-line-strong border-t-ink2" : "border-amber-soft border-t-amber",
        className,
      )}
    />
  );
}

export function Label({ lg = false, className, children, ...rest }: HTMLAttributes<HTMLSpanElement> & { lg?: boolean }) {
  return (
    <span className={cn("font-medium text-ink3", lg ? "text-[13px]" : "text-[12px]", className)} {...rest}>
      {children}
    </span>
  );
}

export function Empty({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("py-2.5 text-[13px] text-pretty text-ink3", className)}>{children}</div>;
}

export function ErrorLine({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span role="alert" className={cn("text-[12.5px] text-red-text", className)}>
      {children}
    </span>
  );
}

export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-card border border-line bg-surface", className)} {...rest}>
      {children}
    </div>
  );
}

/** A quiet explanation at the foot of a card. */
export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start gap-2 bg-paper px-4 py-2.5 text-[12.5px] text-ink2", className)}>
      <Info className="mt-0.5 size-[13px] shrink-0 text-ink3" />
      <span className="text-pretty">{children}</span>
    </div>
  );
}

export function Tag({ variant = "default", children }: { variant?: "default" | "ink" | "dashed"; children: ReactNode }) {
  return (
    <span
      className={cn(
        "rounded px-1.5 text-[11.5px]",
        variant === "default" && "bg-sunken text-ink2",
        variant === "ink" && "bg-ink font-medium text-white",
        variant === "dashed" && "border border-dashed border-ink3 font-medium",
      )}
    >
      {children}
    </span>
  );
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[11px] text-ink3", className)}>{children}</span>;
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono", className)}>{children}</span>;
}

/** A segmented control. */
export function Seg<T extends string>({ value, options, onChange }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="flex gap-0.5 rounded-lg bg-sunken p-0.5" role="tablist">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="tab"
          aria-selected={value === o.id}
          className={cn(
            "flex h-6 items-center rounded-md px-2.5 text-[12.5px] whitespace-nowrap text-ink2",
            value === o.id && "bg-surface text-ink shadow-seg",
          )}
          onClick={() => onChange(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A preformatted block: logs, a reply. */
export function Pre({ children, className, ...rest }: HTMLAttributes<HTMLPreElement>) {
  return (
    <pre
      className={cn("m-0 max-h-[420px] overflow-auto bg-paper px-4 py-3.5 font-mono text-[12.5px] leading-relaxed wrap-break-word whitespace-pre-wrap text-ink1", className)}
      {...rest}
    >
      {children}
    </pre>
  );
}
