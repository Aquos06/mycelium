// The builder: who can write a module (rpc.build.coders), and choosing the default (rpc.build.default).

import { rpc } from "./rpc";
import { coderListSchema, type CoderList } from "@/lib/schemas";

export function fetchCoders(): Promise<CoderList> {
  return rpc("rpc.build.coders", {}, 10, coderListSchema);
}

/** The coder a build gets when it names none. The builder keeps the choice across restarts. */
export function chooseCoder(coder: string): Promise<CoderList> {
  return rpc("rpc.build.default", { coder }, 10, coderListSchema);
}
