"use client";

// The query client, and the defaults that matter.
//
// Created inside useState rather than at module scope: a module-level client is shared by every request
// on the server and would leak one visitor's cache into another's page.

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";

/** A 401 means the token is wrong, a 400 means the request is; neither gets better by retrying. A 504
 *  (nobody answered on the bus) and a network error get one retry. */
export function retry(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry, refetchOnWindowFocus: false, staleTime: 10_000 },
          mutations: { retry: false },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
