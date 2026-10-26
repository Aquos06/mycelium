// The model gateway's domain: rpc.llm.config and rpc.llm.usage (services/gateway/schemas).

import { z } from "zod";
import { keyStateSchema, replySchema } from "./vocabulary";

export const providerInfoSchema = z.looseObject({
  kind: z.string(),
  model: z.string().default(""),
  endpoint: z.string().nullable().default(null),
  key_env: z.string().nullable().default(null),
  key_state: keyStateSchema,
  max_tokens: z.number().default(0),
  price_in_per_m: z.number().default(0),
  price_out_per_m: z.number().default(0),
});
export type ProviderInfo = z.infer<typeof providerInfoSchema>;

export const slotInfoSchema = z.looseObject({
  task: z.string().default("complete"),
  active: z.string(),
  shadow: z.string().nullable().default(null),
  providers: z.record(z.string(), providerInfoSchema),
});
export type SlotInfo = z.infer<typeof slotInfoSchema>;

export const configReplySchema = replySchema.extend({
  budget_usd_month: z.number().nullable().default(null),
  slots: z.record(z.string(), slotInfoSchema).default({}),
});
export type ConfigReply = z.infer<typeof configReplySchema>;

export const usageReplySchema = replySchema.extend({
  month: z.string().default(""),
  usd: z.number().default(0),
  calls: z.number().default(0),
  input_tokens: z.number().default(0),
  output_tokens: z.number().default(0),
  budget_usd_month: z.number().nullable().default(null),
});
export type UsageReply = z.infer<typeof usageReplySchema>;
