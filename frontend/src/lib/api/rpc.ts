// Request/reply on any rpc.* subject, through the gateway. The body is the responder's own reply:
// a 200 with {ok: false, error} means the service answered and said no, which is data, not a throw.
// A 400 (not an rpc subject) or a 504 (nobody answered) is a throw, like any other refusal.

import { API, apiFetch, type Parser } from "./client";
import { replySchema, type Json, type Reply } from "@/lib/schemas";

export function rpc<T extends Reply = Reply>(
  subject: string,
  payload: Json = {},
  timeout?: number,
  schema: Parser<T> = replySchema as unknown as Parser<T>,
): Promise<T> {
  return apiFetch<T>(`${API}/rpc/${subject}`, {
    method: "POST",
    body: { payload, timeout },
    parse: { schema, what: subject },
    mock: async () => (await import("@/lib/mock")).mockRpc(subject, payload) as T,
    mockDelay: 80,
  });
}
