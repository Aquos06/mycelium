// The builder's domain: rpc.build.coders and rpc.build.default (services/builder/schemas/rpc.py), and
// rpc.build.get (mycelium_sdk/build.py).

import { z } from "zod";
import { replySchema } from "./vocabulary";

export const coderInfoSchema = z.looseObject({
  name: z.string(),
  description: z.string().default(""),
  ready: z.boolean(),
  reason: z.string().nullable().default(null), // why it cannot build now
});
export type CoderInfo = z.infer<typeof coderInfoSchema>;

/** Who can write a module, and which one a build gets when it names none. Both rpc.build.* calls answer it. */
export const coderListSchema = replySchema.extend({
  default: z.string().default(""),
  seed: z.string().default(""), // BUILDER_CODER: the default until one is chosen
  coders: z.array(coderInfoSchema).default([]),
});
export type CoderList = z.infer<typeof coderListSchema>;

/** rpc.build.get: one build's record (mycelium_sdk.build.BuildRecord), the part the app reads: how it ended. */
export const buildRecordSchema = replySchema.extend({
  id: z.string().default(""),
  name: z.string().default(""),
  status: z.enum(["queued", "building", "done", "failed"]).catch("building"),
  stage: z.string().nullable().default(null), // where it is, or where a failed one stopped
  // a failed build's error; the same key as a refusal's, and so the same type (none is undefined, not null)
  error: z
    .string()
    .nullish()
    .transform((v) => v ?? undefined),
  version: z.string().nullable().default(null),
  finished: z.string().nullable().default(null),
});
export type BuildRecord = z.infer<typeof buildRecordSchema>;
