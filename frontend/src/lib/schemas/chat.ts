// The chat domain: what the gateway answers when you say something (services/web/chat/schemas.py), and
// the bus messages a conversation is assembled from (services/main/schemas.py), read off the socket.

import { z } from "zod";
import { envelopeSchema } from "./vocabulary";

export const sentSchema = z.object({
  ok: z.literal(true),
  id: z.string(),
  thread: z.string(),
});
export type Sent = z.infer<typeof sentSchema>;

/** sense.chat: what you (or any channel) said. */
export const senseChatSchema = envelopeSchema.extend({
  channel: z.string(),
  thread: z.string(),
  text: z.string(),
});
export type SenseChat = z.infer<typeof senseChatSchema>;

/** out.say: Main's reply. */
export const saySchema = envelopeSchema.extend({
  channel: z.string(),
  thread: z.string(),
  text: z.string().default(""),
});
export type Say = z.infer<typeof saySchema>;

/** out.ask: a question with choices; `ref` is what the answer refers to. */
export const askSchema = saySchema.extend({
  choices: z.array(z.string()).default([]),
  ref: z.string().optional(),
});
export type Ask = z.infer<typeof askSchema>;

export const toolCallSchema = z.looseObject({
  name: z.string(),
  ok: z.boolean().optional(),
  error: z.string().nullable().optional(),
});

/** trace.plan: how Main made a reply. */
export const planTraceSchema = envelopeSchema.extend({
  channel: z.string().optional(),
  thread: z.string().optional(),
  input: z.string().optional(),
  modules: z.array(z.string()).default([]),
  tools: z.array(toolCallSchema).default([]),
  cost_usd: z.number().default(0),
  rounds: z.number().default(0),
  reply_id: z.string().optional(),
  error: z.string().nullable().default(null),
  latency_ms: z.number().default(0),
  pack: z.looseObject({ items: z.array(z.looseObject({ note: z.string(), why: z.string().optional() })).default([]) }).optional(),
  recall_error: z.string().nullable().optional(),
});
export type PlanTrace = z.infer<typeof planTraceSchema>;
