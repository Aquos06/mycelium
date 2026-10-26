"use client";

// localStorage as an external store: one parsed value per key, re-read only when the raw string changes,
// every hook on that key notified on a write. On the server a key reads its fallback.

import { useSyncExternalStore } from "react";

type Subscribe = (cb: () => void) => () => void;

const listeners = new Map<string, Set<() => void>>();
const cache = new Map<string, { raw: string | null; value: unknown }>();
// One subscriber function per key, kept: a fresh closure per render would make React unsubscribe and
// resubscribe every listener on every render of every component on that key.
const subscribers = new Map<string, Subscribe>();

function rawOf(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** The parsed value under `key`, the same reference while the stored string is unchanged. */
export function readStored<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  const raw = rawOf(key);
  const hit = cache.get(key);
  if (hit && hit.raw === raw) return hit.value as T;
  let value: T = fallback;
  if (raw !== null) {
    try {
      value = JSON.parse(raw) as T;
    } catch {
      /* a bad value reads as the fallback */
    }
  }
  cache.set(key, { raw, value });
  return value;
}

/** Write `value` under `key` and tell every hook on it. A write of the same string tells nobody. */
export function writeStored(key: string, value: unknown): void {
  const raw = JSON.stringify(value);
  if (rawOf(key) === raw) return;
  try {
    window.localStorage.setItem(key, raw);
  } catch {
    cache.set(key, { raw, value }); // storage refused: this session still sees it
  }
  for (const l of listeners.get(key) ?? []) l();
}

function subscriberFor(key: string): Subscribe {
  let sub = subscribers.get(key);
  if (sub) return sub;
  sub = (cb) => {
    let set = listeners.get(key);
    if (!set) listeners.set(key, (set = new Set()));
    set.add(cb);
    const onStorage = (e: StorageEvent) => {
      if (e.key === key || e.key === null) cb();
    };
    window.addEventListener("storage", onStorage);
    return () => {
      set!.delete(cb);
      window.removeEventListener("storage", onStorage);
    };
  };
  subscribers.set(key, sub);
  return sub;
}

/** `fallback` must be a stable reference (a module constant), or the hook re-renders on every call. */
export function useStored<T>(key: string, fallback: T): [T, (v: T) => void] {
  const value = useSyncExternalStore(
    subscriberFor(key),
    () => readStored(key, fallback),
    () => fallback,
  );
  return [value, (v: T) => writeStored(key, v)];
}
