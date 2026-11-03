// The builder's domain: rpc.build.coders and rpc.build.default (services/builder/schemas/rpc.py).

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
