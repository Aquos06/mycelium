"use client";

// The clock, as an external store. A screen that shows "now", "2m" or the greeting subscribes here and
// re-renders on the tick; on the server and during hydration it reads null, so the first paint cannot
// disagree with the HTML (there is no clock in it).

import { useSyncExternalStore } from "react";

export const TICK_MS = 15_000;

const listeners = new Set<() => void>();
let current = Date.now();
let timer: ReturnType<typeof setInterval> | undefined;

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  if (!timer) {
    current = Date.now(); // the store may have slept while nothing was subscribed
    timer = setInterval(() => {
      current = Date.now();
      for (const l of listeners) l();
    }, TICK_MS);
  }
  return () => {
    listeners.delete(cb);
    if (listeners.size === 0 && timer) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

/** The time, fresh to within TICK_MS; null until mounted. */
export function useNow(): number | null {
  return useSyncExternalStore(subscribe, () => current, () => null);
}

/** False on the server and on the first client render, true after hydration. */
export function useMounted(): boolean {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}
