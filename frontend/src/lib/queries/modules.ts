"use client";

// The modules the supervisor knows, kept fresh: refetched every 20 s and a moment after any sys.* event
// (a deploy, a stop, a reconcile). The core services' state comes from a probe where one exists.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import {
  askModule,
  deployModule,
  describeError,
  fetchModuleViews,
  listModules,
  moduleLogs,
  modulesHealth,
  probe,
  removeModule,
  stopModule,
} from "@/lib/api";
import { useBus } from "@/lib/bus";
import { useNow } from "@/lib/clock";
import { CORE } from "@/lib/core";
import type { Json, ModuleHealth, ModuleRow } from "@/lib/schemas";
import { queryKeys } from "./keys";

export const MODULES_POLL_MS = 20_000;
export const CORE_POLL_MS = 30_000;
export const VIEWS_POLL_MS = 60_000;

export interface ModulesState {
  modules: ModuleRow[];
  grown: string[]; // the modules the builder grew: the ones it can delete
  folders: string[]; // every module folder on disk; one listed and not here has lost its folder
  health: Record<string, ModuleHealth>;
  loading: boolean;
  error: string | null; // the supervisor did not answer
  refresh: () => void;
}

export function useModules(): ModulesState {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: queryKeys.modules(),
    queryFn: async () => {
      const r = await listModules();
      if (!r.ok) throw new Error(r.error ?? "the supervisor said no");
      return { ...r, modules: r.modules.slice().sort((a, b) => a.name.localeCompare(b.name)) };
    },
    refetchInterval: MODULES_POLL_MS,
  });
  const health = useQuery({
    queryKey: queryKeys.modulesHealth(),
    queryFn: async () => {
      const r = await modulesHealth();
      return r.ok ? r.modules : {};
    },
    enabled: (list.data?.modules.length ?? 0) > 0,
    refetchInterval: MODULES_POLL_MS,
  });

  // a deploy, stop or reconcile just happened: look again in a moment
  const { events, status } = useBus();
  const lastSys = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) if (events[i].subject.startsWith("sys.")) return events[i].seq;
    return 0;
  }, [events]);
  useEffect(() => {
    if (!lastSys || status !== "live") return;
    const t = window.setTimeout(() => {
      void qc.invalidateQueries({ queryKey: queryKeys.modules() });
      void qc.invalidateQueries({ queryKey: queryKeys.modulesHealth() });
    }, 800);
    return () => window.clearTimeout(t);
  }, [lastSys, status, qc]);

  return {
    modules: list.data?.modules ?? [],
    grown: list.data?.grown ?? [],
    folders: list.data?.folders ?? [],
    health: health.data ?? {},
    loading: list.isPending,
    error: list.error ? describeError(list.error, "the supervisor") : null,
    refresh: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.modules() });
      void qc.invalidateQueries({ queryKey: queryKeys.modulesHealth() });
    },
  };
}

export type CoreUp = "up" | "down" | "unknown";

/** Whether each core service answers: a probe where one exists, otherwise recent evidence on the bus. */
export function useCoreStatus(): Record<string, CoreUp> {
  const { events } = useBus();
  const now = useNow() ?? 0;
  const probes = useQuery({
    queryKey: queryKeys.core(),
    queryFn: async () => {
      const out: Record<string, CoreUp> = {};
      await Promise.all(
        CORE.filter((c) => c.probe).map(async (c) => {
          out[c.name] = (await probe(c.probe!, c.probePayload ?? {})) ? "up" : "down";
        }),
      );
      return out;
    },
    refetchInterval: CORE_POLL_MS,
  });
  return useMemo(() => {
    const recent = events.filter((e) => now - new Date(e.received).getTime() < 3600_000);
    const out: Record<string, CoreUp> = {};
    for (const c of CORE) {
      if (c.probe) out[c.name] = probes.data?.[c.name] ?? "unknown";
      else if (c.evidence) out[c.name] = recent.some(c.evidence) ? "up" : "unknown";
      else out[c.name] = "unknown";
    }
    return out;
  }, [events, probes.data, now]);
}

/** The container's last lines, fetched when a screen asks (`enabled`). */
export function useModuleLogs(name: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.moduleLogs(name),
    queryFn: async () => {
      const r = await moduleLogs(name, 200);
      return r.ok ? r.logs || "(empty)" : (r.error ?? "no logs");
    },
    enabled,
    staleTime: 0,
  });
}

/** Pause (rpc.sys.stop) or start / rebuild (rpc.sys.deploy) one module; the list refreshes after. */
export function useModuleAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ name, action }: { name: string; action: "deploy" | "stop" }) => {
      const r = await (action === "deploy" ? deployModule(name) : stopModule(name));
      if (!r.ok) throw new Error(r.error ?? `${action} failed`);
      return r;
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.modules() });
      void qc.invalidateQueries({ queryKey: queryKeys.modulesHealth() });
    },
  });
}

/** Delete a module the builder grew (rpc.build.remove). A refusal (it is being built, it is hand-written) throws
 *  with the builder's reason; the list refreshes either way. */
export function useRemoveModule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      const r = await removeModule(name);
      if (!r.ok) throw new Error(r.error ?? "the builder said no");
      return r;
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.modules() });
      void qc.invalidateQueries({ queryKey: queryKeys.modulesHealth() });
    },
  });
}

/** Whether the builder can delete this module: one it grew, or one still listed whose folder is gone. A
 *  hand-written one (its folder in modules/) is the repo's to remove. */
export function deletable(name: string, state: Pick<ModulesState, "grown" | "folders">): boolean {
  return state.grown.includes(name) || !state.folders.includes(name);
}

/** Ask a module directly: rpc.mod.<name>.<action> with JSON arguments. The reply is shown as is. */
export function useAskModule() {
  return useMutation({
    mutationFn: ({ name, action, args }: { name: string; action: string; args: Json }) => askModule(name, action, args),
  });
}

/** What a module's page shows of its data, read again every minute and as soon as the module says something on
 *  the bus (an entry logged, a total changed): its own events are the sign its data moved. */
export function useModuleViews(name: string) {
  const qc = useQueryClient();
  const { events } = useBus();
  const views = useQuery({
    queryKey: queryKeys.moduleViews(name),
    queryFn: () => fetchModuleViews(name),
    refetchInterval: VIEWS_POLL_MS,
  });
  const latest = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) if (events[i].subject.startsWith(`mod.${name}.`)) return events[i].seq;
    return null;
  }, [events, name]);
  useEffect(() => {
    if (latest === null) return;
    const t = setTimeout(() => void qc.invalidateQueries({ queryKey: queryKeys.moduleViews(name) }), 400);
    return () => clearTimeout(t);
  }, [latest, name, qc]);
  return views;
}

/** One sentence for a module page the gateway could not build, or null. */
export function viewsError(e: Error | null): string | null {
  return e ? describeError(e, "the gateway") : null;
}
