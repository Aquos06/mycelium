// The supervisor's rpc.sys.*, a module's own rpc.mod.<name>.<action>, a module's page (its views), and deleting a
// module (the builder's rpc.build.remove: grown/ is the builder's to change).

import { API, apiFetch } from "./client";
import { rpc } from "./rpc";
import {
  healthReplySchema,
  listReplySchema,
  logsReplySchema,
  moduleViewsSchema,
  removedSchema,
  type HealthReply,
  type Json,
  type ListReply,
  type LogsReply,
  type ModuleViews,
  type Removed,
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

/** Delete a module the builder grew: the supervisor copies its data aside and removes the rest, then its folder
 *  leaves grown/ in one commit (its tag keeps the code). It stops the module and copies its data: give it time. */
export function removeModule(name: string): Promise<Removed> {
  return rpc("rpc.build.remove", { name }, 150, removedSchema, MOCK_REMOVE_MS);
}

// in mock mode it answers as late as a deletion does, after its row has left the list
const MOCK_REMOVE_MS = 600;

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
