"use client";

// The responsive shell. Two layouts, one component:
//
//   < md   a single column with the tab bar at the bottom (the phone)
//   >= md  the design's 1440 layout: the sidebar on the left, one screen on the right
//
// Also the keyboard: ⌘J opens the voice screen, Esc leaves it. And the banner when the gateway is away.

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useBus } from "@/lib/bus";
import { ROUTES } from "@/lib/nav";
import { Button } from "./Button";
import { Sidebar } from "./Sidebar";
import { TabBar } from "./TabBar";

export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const bus = useBus();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        if (pathname === ROUTES.voice) router.back();
        else router.push(ROUTES.voice);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pathname, router]);

  return (
    <div className="flex h-dvh w-full flex-col overflow-hidden md:flex-row">
      <Sidebar />
      <main className="relative flex min-h-0 min-w-0 flex-1 flex-col bg-surface">
        {bus.status === "offline" && (
          <div role="status" className="flex items-center gap-2.5 border-b border-amber-line bg-amber-soft px-4 py-2 text-[12.5px] text-amber-text">
            <span>The web gateway is not reachable. Reconnecting…</span>
            <Button size="sm" className="ml-auto" onClick={bus.retry}>
              Try now
            </Button>
          </div>
        )}
        {bus.status === "refused" && (
          <div role="status" className="flex items-center gap-2.5 border-b border-amber-line bg-amber-soft px-4 py-2 text-[12.5px] text-amber-text">
            <span>
              The web gateway does not serve this page&apos;s origin. Add it to <span className="font-mono">WEB_CORS_ORIGINS</span> and restart the gateway.
            </span>
          </div>
        )}
        {children}
      </main>
      <TabBar />
    </div>
  );
}
