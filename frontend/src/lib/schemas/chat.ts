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

// ---- blocks ---------------------------------------------------------------------------------------------
//
// What Main shows under a reply (services/main/blocks.py): a module's data as a table, a chart, stats, details or
// a meter. Every value comes twice, as data (`v`: to sort and to plot) and as it reads (`s`: "NT$350", "Nov 7"),
// so the app never formats a value Main sent; it only places it.
export const cellSchema = z.object({
  v: z.union([z.number(), z.string(), z.boolean(), z.null()]).default(null),
  s: z.string().default(""),
});
export type Cell = z.infer<typeof cellSchema>;

export const blockFormatSchema = z.enum(["text", "number", "money", "percent", "date", "bool"]).catch("text");
export type BlockFormat = z.infer<typeof blockFormatSchema>;

export const blockColumnSchema = z.object({
  key: z.string(),
  label: z.string(),
  format: blockFormatSchema,
  prefix: z.string().default(""), // an axis tick's: "NT$"
  suffix: z.string().default(""), // "%"
});
export type BlockColumn = z.infer<typeof blockColumnSchema>;

export const figureSchema = z.object({ label: z.string(), value: cellSchema });
export type Figure = z.infer<typeof figureSchema>;

export const tableBlockSchema = z.object({
  kind: z.literal("table"),
  title: z.string().default(""),
  columns: z.array(blockColumnSchema).min(1),
  rows: z.array(z.array(cellSchema)).default([]),
  total: z.number().default(0), // rows in the data; `rows` may hold fewer
  text: z.string().default(""),
});
export type TableBlock = z.infer<typeof tableBlockSchema>;

export const chartBlockSchema = z.object({
  kind: z.literal("chart"),
  chart: z.enum(["bar", "line", "area"]).catch("bar"),
  title: z.string().default(""),
  x: blockColumnSchema,
  series: z.array(blockColumnSchema).min(1).max(4),
  points: z.array(z.object({ x: cellSchema, y: z.array(cellSchema) })).default([]),
  total: z.number().default(0),
  text: z.string().default(""),
});
export type ChartBlock = z.infer<typeof chartBlockSchema>;

export const statsBlockSchema = z.object({
  kind: z.literal("stats"),
  title: z.string().default(""),
  stats: z.array(figureSchema).min(1),
  text: z.string().default(""),
});
export type StatsBlock = z.infer<typeof statsBlockSchema>;

export const detailsBlockSchema = z.object({
  kind: z.literal("details"),
  title: z.string().default(""),
  items: z.array(figureSchema).min(1),
  text: z.string().default(""),
});
export type DetailsBlock = z.infer<typeof detailsBlockSchema>;

export const meterBlockSchema = z.object({
  kind: z.literal("meter"),
  title: z.string().default(""),
  label: z.string(),
  value: cellSchema,
  max: cellSchema,
  text: z.string().default(""),
});
export type MeterBlock = z.infer<typeof meterBlockSchema>;

export const blockSchema = z.discriminatedUnion("kind", [tableBlockSchema, chartBlockSchema, statsBlockSchema, detailsBlockSchema, meterBlockSchema]);
export type Block = z.infer<typeof blockSchema>;

/** A reply's blocks, each read on its own: one this app cannot read (a kind it does not know yet) is left out,
 *  never the reply with it. */
export const blocksSchema = z
  .array(z.unknown())
  .default([])
  .transform((xs) =>
    xs.flatMap((x) => {
      const b = blockSchema.safeParse(x);
      return b.success ? [b.data] : [];
    }),
  );

/** out.say: Main's reply, and the blocks under it (a module's data as a table, a chart, ...: above). */
export const saySchema = envelopeSchema.extend({
  channel: z.string(),
  thread: z.string(),
  text: z.string().default(""),
  blocks: blocksSchema,
});
export type Say = z.infer<typeof saySchema>;

/** out.ask: a question with choices; `ref` is what the answer refers to. */
export const askSchema = saySchema.extend({
  choices: z.array(z.string()).default([]),
  ref: z.string().optional(),
});
export type Ask = z.infer<typeof askSchema>;

export const progressStepSchema = z.object({
  text: z.string(),
  state: z.enum(["done", "failed", "active", "pending"]).catch("pending"),
  since: z.string().nullable().optional(), // an active step: when it began
});
export type ProgressStep = z.infer<typeof progressStepSchema>;

/** out.progress: a job you are waiting on (a build Main started), one message that changes in place. Every update
 *  carries the same `ref` and the whole picture; keep the finished one, else the highest `seq`. */
export const progressSchema = envelopeSchema.extend({
  channel: z.string(),
  thread: z.string(),
  ref: z.string(),
  seq: z.number().default(0),
  title: z.string(),
  state: z.enum(["running", "done", "failed"]).catch("running"),
  steps: z.array(progressStepSchema).default([]),
  text: z.string().default(""),
});
export type Progress = z.infer<typeof progressSchema>;

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
