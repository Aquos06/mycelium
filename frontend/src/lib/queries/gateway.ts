"use client";

// The model gateway: its slots and providers, and the month's spend. Both re-read once a minute, which
// is as fast as providers.yaml or the budget can change (a restart).

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { describeError, fetchConfig, fetchUsage } from "@/lib/api";
import { queryKeys } from "./keys";

export const GATEWAY_POLL_MS = 60_000;

export function useGatewayConfig() {
  return useQuery({
    queryKey: queryKeys.config(),
    queryFn: async () => {
      const r = await fetchConfig();
      if (!r.ok) throw new Error(r.error ?? "the gateway said no");
      return r;
    },
    refetchInterval: GATEWAY_POLL_MS,
  });
}

export function useUsage() {
  return useQuery({
    queryKey: queryKeys.usage(),
    queryFn: async () => {
      const r = await fetchUsage();
      return r.ok ? r : null;
    },
    refetchInterval: GATEWAY_POLL_MS,
  });
}

/** Key env vars an ACTIVE provider needs and does not have: what the home page and the sidebar warn about. */
export function useMissingKeys(): string[] {
  const { data } = useGatewayConfig();
  return useMemo(() => {
    if (!data) return [];
    return [
      ...new Set(
        Object.values(data.slots).flatMap((slot) => {
          const p = slot.providers[slot.active];
          return p && p.key_state === "missing" && p.key_env ? [p.key_env] : [];
        }),
      ),
    ];
  }, [data]);
}

/** One sentence for a gateway that did not answer, or null. */
export function gatewayError(e: Error | null): string | null {
  return e ? describeError(e, "the gateway") : null;
}
