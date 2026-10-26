// The gateway about itself. /system/health is also the login check: a 401 here means the token is wrong.

import { API, apiFetch } from "./client";
import { healthSchema, type Health } from "@/lib/schemas";

export function fetchHealth(): Promise<Health> {
  return apiFetch<Health>(`${API}/system/health`, {
    parse: { schema: healthSchema, what: "the gateway's health" },
    mock: async () => (await import("@/lib/mock")).mockHealth(),
  });
}
