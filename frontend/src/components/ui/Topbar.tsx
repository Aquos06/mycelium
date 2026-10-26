"use client";

// The 48px bar over a screen: a crumb, a title, and the screen's own controls on the right.

import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Topbar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <header className={cn("relative flex h-12 shrink-0 items-center gap-2 border-b border-sunken px-6", className)}>{children}</header>
  );
}

export function Crumb({ href, children }: { href?: string; children: ReactNode }) {
  return href ? (
    <Link href={href} className="text-ink3 no-underline hover:text-ink">
      {children}
    </Link>
  ) : (
    <span className="text-ink3">{children}</span>
  );
}

export const Sep = () => <span className="text-line-strong">/</span>;

export function Title({ mono = false, className, children }: { mono?: boolean; className?: string; children: ReactNode }) {
  return <span className={cn("font-medium", mono && "font-mono", className)}>{children}</span>;
}

export function Right({ children }: { children: ReactNode }) {
  return <div className="ml-auto flex items-center gap-1.5">{children}</div>;
}

/** The scrolling body under a Topbar; `paper` for the home page's warmer ground. */
export function Page({ paper = false, className, children }: { paper?: boolean; className?: string; children: ReactNode }) {
  return <div className={cn("min-h-0 flex-1 overflow-y-auto", paper && "bg-paper", className)}>{children}</div>;
}

export function PageInner({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("mx-auto flex flex-col gap-8 px-4 pt-5 pb-12 md:px-6 md:pt-7 md:pb-16", className)}>{children}</div>;
}
