// The modules domain: what the supervisor answers on rpc.sys.* (services/supervisor).

import { z } from "zod";
import { replySchema } from "./vocabulary";

export const manifestSchema = z.looseObject({
  name: z.string(),
  version: z.string().default(""),
  purpose: z.string().default(""),
  need: z.string().default(""),
  subscribes: z.array(z.string()).default([]),
  emits: z.array(z.string()).default([]),
  requests: z.array(z.string()).default([]),
  hooks: z.looseObject({ interval_seconds: z.array(z.number()).default([]) }).default({ interval_seconds: [] }),
  permissions: z.looseObject({ network: z.boolean().default(false), actuation: z.boolean().default(false) }).default({
    network: false,
    actuation: false,
  }),
  resources: z.looseObject({ memory_mb: z.number().optional(), cpus: z.number().optional() }).default({}),
});
export type Manifest = z.infer<typeof manifestSchema>;

export const moduleRowSchema = z.looseObject({
  name: z.string(),
  version: z.string().default(""),
  status: z.string().default(""), // the supervisor's registry: running, stopped, failed, building
  image: z.string().nullable().default(null),
  manifest: manifestSchema,
  container: z.string().nullable().default(null), // docker's view, or null when there is no container
});
export type ModuleRow = z.infer<typeof moduleRowSchema>;

export const listReplySchema = replySchema.extend({
  modules: z.array(moduleRowSchema).default([]),
});
export type ListReply = z.infer<typeof listReplySchema>;

export const moduleHealthSchema = z.looseObject({
  ok: z.boolean(),
  status: z.string().optional(),
  error: z.string().optional(),
});
export type ModuleHealth = z.infer<typeof moduleHealthSchema>;

export const healthReplySchema = replySchema.extend({
  modules: z.record(z.string(), moduleHealthSchema).default({}),
});
export type HealthReply = z.infer<typeof healthReplySchema>;

export const logsReplySchema = replySchema.extend({
  name: z.string().optional(),
  logs: z.string().optional(),
});
export type LogsReply = z.infer<typeof logsReplySchema>;
