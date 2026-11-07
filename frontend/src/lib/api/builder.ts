// The builder: who can write a module (rpc.build.coders), choosing the default (rpc.build.default), and one
// build's record (rpc.build.get).

import { rpc } from "./rpc";
import { buildRecordSchema, coderListSchema, type BuildRecord, type CoderList } from "@/lib/schemas";

export function fetchCoders(): Promise<CoderList> {
  return rpc("rpc.build.coders", {}, 10, coderListSchema);
}

/** The coder a build gets when it names none. The builder keeps the choice across restarts. */
export function chooseCoder(coder: string): Promise<CoderList> {
  return rpc("rpc.build.default", { coder }, 10, coderListSchema);
}

/** One build's record: where it is, or how it ended. */
export function fetchBuild(id: string): Promise<BuildRecord> {
  return rpc("rpc.build.get", { build_id: id }, 10, buildRecordSchema);
}
