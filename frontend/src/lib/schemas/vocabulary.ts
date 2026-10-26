// The closed sets that cross domains, and the one shape every bus reply shares.
//
// `vocabulary.ts` is the only module the other schema files may import; nothing here imports a
// sibling, so there is no cycle to break later.

import { z } from "zod";

/** A payload whose shape belongs to whichever service published it. */
export const jsonSchema = z.record(z.string(), z.unknown());
export type Json = z.infer<typeof jsonSchema>;

/** What every bus reply and every gateway refusal share: `ok`, and `error` when it is false. */
export const replySchema = z.looseObject({
  ok: z.boolean(),
  error: z.string().optional(),
});
export type Reply = z.infer<typeof replySchema>;

/** The envelope every bus message carries (mycelium_sdk.Envelope). */
export const envelopeSchema = z.looseObject({
  id: z.string(),
  ts: z.string().optional(),
  source: z.string().optional(),
  cause: z.string().nullable().default(null),
  hops: z.number().optional(),
});
export type Envelope = z.infer<typeof envelopeSchema>;

/** Whether a provider's key is in the gateway's environment (services/gateway/schemas/describe.py). */
export const keyStateSchema = z.enum(["ok", "missing", "not-needed"]);
export type KeyState = z.infer<typeof keyStateSchema>;

/** A module's state in one word: the supervisor's registry and docker's view, read together (lib/status.ts). */
export const statusKindSchema = z.enum(["running", "growing", "failed", "paused", "seed", "unknown"]);
export type StatusKind = z.infer<typeof statusKindSchema>;

/** A place on the bus: the subject prefixes, each with its own hue (lib/domains.ts). */
export const domainSchema = z.enum(["sense", "brain", "mod", "build", "sys", "out", "trace", "rpc"]);
export type Domain = z.infer<typeof domainSchema>;
