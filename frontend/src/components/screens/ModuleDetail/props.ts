import type { CoreService } from "@/lib/core";
import type { ModuleHealth, ModuleRow } from "@/lib/schemas";

/** [label, value, monospace] */
export type Prop = [string, string, boolean];

export function moduleProps(m: ModuleRow, health?: ModuleHealth): Prop[] {
  const man = m.manifest;
  return [
    ["Status", m.status + (m.container ? ` · container ${m.container}` : ""), false],
    ["Health", health ? (health.ok ? "ok" : (health.error ?? health.status ?? "not ok")) : "—", false],
    ["Version", m.version, true],
    ["Interval", man.hooks.interval_seconds.length ? man.hooks.interval_seconds.map((s) => `${s} s`).join(", ") : "none", true],
    ["Memory", `${man.resources.memory_mb ?? "—"} MB`, true],
    ["CPU", String(man.resources.cpus ?? "—"), true],
    ["Network", man.permissions.network ? "on" : "off", false],
    ["Actuation", man.permissions.actuation ? "on" : "off", false],
    ["Image", m.image ?? "not built", true],
  ];
}

export function coreProps(c: Pick<CoreService, "name" | "optional" | "probe">): Prop[] {
  return [
    ["Kind", c.optional ? "core service · compose profile" : "core service", false],
    ["Runs as", `docker compose service ${c.name}`, true],
    ["Probe", c.probe ?? "none, seen on the bus", true],
  ];
}
