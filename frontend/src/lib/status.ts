// A module's state in one word, from the supervisor's registry status and docker's container state.

import type { ModuleRow, StatusKind } from "@/lib/schemas";

export const STATUS_LABEL: Record<StatusKind, string> = {
  running: "Running",
  growing: "Growing",
  failed: "Failed",
  paused: "Paused",
  seed: "Seed",
  unknown: "Unknown",
};

export function statusOf(m: Pick<ModuleRow, "status" | "container">): StatusKind {
  const s = (m.status || "").toLowerCase();
  const c = (m.container || "").toLowerCase();
  if (s === "building" || s === "deploying") return "growing";
  if (s === "failed" || s === "error" || c === "dead") return "failed";
  if (s === "running") return c && c !== "running" ? "failed" : "running";
  if (s === "stopped" || c === "exited" || c === "paused") return "paused";
  return s ? "unknown" : "seed";
}
