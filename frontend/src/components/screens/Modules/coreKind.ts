import type { CoreUp } from "@/lib/queries";
import type { StatusKind } from "@/lib/schemas";

/** A core service's probe result as a pill. */
export function coreKind(up: CoreUp, optional = false): { kind: StatusKind; label: string } {
  if (up === "up") return { kind: "running", label: "Running" };
  if (up === "down") return { kind: "failed", label: "Not answering" };
  return { kind: "unknown", label: optional ? "Not seen" : "No probe" };
}
