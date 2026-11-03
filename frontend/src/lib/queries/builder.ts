"use client";

// The builder's coders: which can build now and which is the default. Re-read every 30 s, because
// "ready" follows the supervisor's agents and the gateway's keys.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { chooseCoder, describeError, fetchCoders } from "@/lib/api";
import { queryKeys } from "./keys";

export const CODERS_POLL_MS = 30_000;

export function useCoders() {
  return useQuery({
    queryKey: queryKeys.coders(),
    queryFn: async () => {
      const r = await fetchCoders();
      if (!r.ok) throw new Error(r.error ?? "the builder said no");
      return r;
    },
    refetchInterval: CODERS_POLL_MS,
  });
}

/** Make one coder the default; the list is replaced by the builder's answer. */
export function useChooseCoder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (coder: string) => {
      const r = await chooseCoder(coder);
      if (!r.ok) throw new Error(r.error ?? "the builder said no");
      return r;
    },
    onSuccess: (list) => qc.setQueryData(queryKeys.coders(), list),
  });
}

/** One sentence for a builder that did not answer, or null. */
export function builderError(e: Error | null): string | null {
  return e ? describeError(e, "the builder") : null;
}
