// What a screen needs around it to render in jsdom: the query client, a bus with fixed events, and
// Next's navigation hooks replaced (there is no router here). MOCK mode is on, so every call answers
// from lib/mock without a gateway.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";
import { BusContext, type BusState } from "@/lib/bus";
import type { BusEvent } from "@/lib/schemas";

export const router = { push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() };

export function mockNavigation(pathname = "/") {
  vi.mock("next/navigation", () => ({
    useRouter: () => router,
    usePathname: () => pathname,
    useSearchParams: () => new URLSearchParams(),
    redirect: vi.fn(),
    notFound: vi.fn(),
  }));
}

export function renderScreen(ui: ReactNode, events: BusEvent[], status: BusState["status"] = "live", streams: BusState["streams"] = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const bus: BusState = { events, streams, status, name: "Hansen", retry: () => {} };
  return render(
    <QueryClientProvider client={client}>
      <BusContext.Provider value={bus}>{ui}</BusContext.Provider>
    </QueryClientProvider>,
  );
}

let seq = 0;
/** A bus event on channel web, stamped a minute ago. */
export function event(subject: string, data: BusEvent["data"], received = new Date(Date.now() - 60_000).toISOString()): BusEvent {
  return { seq: ++seq, subject, data, received };
}

export function envelope(id: string, cause: string | null = null) {
  return { id, ts: new Date(Date.now() - 60_000).toISOString(), source: "main", cause, hops: 0 };
}
