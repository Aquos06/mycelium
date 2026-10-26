"use client";

// Below md: the four places, as a bar at the bottom of the phone.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ROUTES, TABS, tabForPath, threadOf } from "@/lib/nav";
import { cn } from "@/lib/utils";

export function TabBar() {
  const pathname = usePathname();
  const tab = tabForPath(pathname);
  return (
    <nav
      aria-label="Main"
      className="flex shrink-0 items-center justify-around border-t border-line bg-sidebar px-2 pt-1.5 pb-[calc(6px+env(safe-area-inset-bottom))] md:hidden"
    >
      {TABS.map((t) => {
        const Icon = t.icon;
        const on = tab === t.id;
        const href = t.id === "chat" ? ROUTES.chat(threadOf(pathname)) : t.href;
        return (
          <Link
            key={t.id}
            href={href}
            aria-current={on ? "page" : undefined}
            className={cn("flex h-11 flex-col items-center justify-center gap-0.5 rounded-row px-2 text-[11px] text-ink2 no-underline", on && "font-medium text-ink")}
          >
            <Icon className="size-[18px]" strokeWidth={on ? 2 : 1.7} />
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
