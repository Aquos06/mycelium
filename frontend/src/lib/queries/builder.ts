"use client";

// The builder's coders: which can build now and which is the default. Re-read every 30 s, because
// "ready" follows the supervisor's agents and the gateway's keys. And one build's record, for a card that
// stopped hearing about it.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { chooseCoder, describeError, fetchBuild, fetchCoders } from "@/lib/api";
import { queryKeys } from "./keys";

export const CODERS_POLL_MS = 30_000;
export const BUILD_POLL_MS = 60_000;

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
    // a poll already on its way could answer after this and put the old default back: stop it first
    onMutate: () => qc.cancelQueries({ queryKey: queryKeys.coders() }),
    onSuccess: (list) => qc.setQueryData(queryKeys.coders(), list),
  });
}

/** One sentence for a builder that did not answer, or null. */
export function builderError(e: Error | null): string | null {
  return e ? describeError(e, "the builder") : null;
}

/** A build's record while `enabled`, read again every minute until it has ended. */
export function useBuild(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.build(id),
    queryFn: async () => {
      const r = await fetchBuild(id);
      if (!r.ok) throw new Error(r.error ?? "the builder said no");
      return r;
    },
    enabled,
    retry: false,
    refetchInterval: (q) => (q.state.data?.status === "done" || q.state.data?.status === "failed" ? false : BUILD_POLL_MS),
  });
}
