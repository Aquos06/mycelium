// The closed sets that cross domains, the one shape every bus reply shares, and the blocks (chat and modules).
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

// ---- blocks ---------------------------------------------------------------------------------------------
//
// A module's data as a table, a chart, stats, details or a meter (mycelium_sdk/blocks.py): what Main shows under
// a reply, and what a module's page shows of its views. Every value comes twice, as data (`v`: to sort and to plot) and as it reads (`s`: "NT$350", "Nov 7"),
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
