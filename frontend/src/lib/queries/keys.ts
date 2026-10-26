// Every query key, in ONE place.
//
// A key built inline is how two call sites end up with ["modules"] and ["modules", 20] and quietly stop
// sharing a cache entry. The factory is the reason that cannot happen, so it is not split by domain with
// the hooks: one file, one vocabulary.

import type { UseQueryOptions } from "@tanstack/react-query";

export const queryKeys = {
  health: () => ["health"] as const,
  modules: () => ["modules"] as const,
  // Its own prefix, not a child of `modules`: ["modules", "health"] would be one hop from being read as
  // a module named "health".
  modulesHealth: () => ["modules-health"] as const,
  moduleLogs: (name: string) => ["module-logs", name] as const,
  core: () => ["core-probes"] as const,
  config: () => ["gateway-config"] as const,
  usage: () => ["gateway-usage"] as const,
};

/** What a screen may pass to a hook: everything but the key and the fetcher, which the hook owns. */
export type Options<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, "queryKey" | "queryFn">;
