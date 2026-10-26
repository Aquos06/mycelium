// The recent bus events over REST: what a page that just opened missed, and the gap after a reconnect.
// The live stream is the socket (lib/bus.tsx), whose address `socketUrl()` in client.ts gives.

import { API, apiFetch } from "./client";
import { eventsPageSchema, type EventsPage } from "@/lib/schemas";

export function fetchEvents(after = 0, limit = 300): Promise<EventsPage> {
  return apiFetch<EventsPage>(`${API}/events?after=${after}&limit=${limit}`, {
    parse: { schema: eventsPageSchema, what: "the recent events" },
    mock: async () => (await import("@/lib/mock")).mockEventsPage(after, limit),
  });
}
