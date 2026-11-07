// The supervisor's rpc.sys.*, a module's own rpc.mod.<name>.<action>, and a module's page (its views).

import { API, apiFetch } from "./client";
import { rpc } from "./rpc";
import {
  healthReplySchema,
  listReplySchema,
  logsReplySchema,
  moduleViewsSchema,
  type HealthReply,
  type Json,
  type ListReply,
  type LogsReply,
  type ModuleViews,
  type Reply,
} from "@/lib/schemas";

export function listModules(): Promise<ListReply> {
  return rpc("rpc.sys.list", {}, 5, listReplySchema);
}

export function modulesHealth(): Promise<HealthReply> {
  return rpc("rpc.sys.health", {}, 8, healthReplySchema);
}

export function moduleLogs(name: string, tail = 200): Promise<LogsReply> {
  return rpc("rpc.sys.logs", { name, tail }, 15, logsReplySchema);
}

/** Build the image from modules/<name> and (re)start it. Long: a first build pulls the base image. */
export function deployModule(name: string): Promise<Reply> {
  return rpc("rpc.sys.deploy", { name }, 600);
}

export function stopModule(name: string): Promise<Reply> {
  return rpc("rpc.sys.stop", { name }, 60);
}

/** Ask a module directly on its own subject. The reply is whatever the module answers. */
export function askModule(name: string, action: string, args: Json): Promise<Reply> {
  return rpc(`rpc.mod.${name}.${action}`, args, 15);
}

/** Is a core service there? Any answer, even a refusal, means yes. */
export async function probe(subject: string, payload: Json = {}): Promise<boolean> {
  try {
    await rpc(subject, payload, 4);
    return true;
  } catch {
    return false;
  }
}

/** What a module's page shows of its data: each view, built by the gateway from what the module answers now. */
export function fetchModuleViews(name: string): Promise<ModuleViews> {
  return apiFetch<ModuleViews>(`${API}/modules/${encodeURIComponent(name)}/views`, {
    parse: { schema: moduleViewsSchema, what: `${name}'s views` },
    mock: async () => (await import("@/lib/mock")).mockModuleViews(name),
  });
}
