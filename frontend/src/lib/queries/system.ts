"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "@/lib/api";
import type { Health } from "@/lib/schemas";
import { queryKeys, type Options } from "./keys";

/** The gateway's health: who it is for, whether it asks for a token, what it holds. */
export function useHealth(options?: Options<Health>) {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: fetchHealth,
    refetchInterval: 60_000,
    ...options,
  });
}
