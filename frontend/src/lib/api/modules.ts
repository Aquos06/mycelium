// The supervisor's rpc.sys.* and a module's own rpc.mod.<name>.<action>.

import { rpc } from "./rpc";
import {
  healthReplySchema,
  listReplySchema,
  logsReplySchema,
  type HealthReply,
  type Json,
  type ListReply,
  type LogsReply,
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
