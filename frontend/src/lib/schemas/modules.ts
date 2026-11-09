// The modules domain: what the supervisor answers on rpc.sys.* (services/supervisor), and a module's page: its
// views, built by the web gateway from what the module answers (services/web/modules).

import { z } from "zod";
import { blockSchema, replySchema } from "./vocabulary";

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
  folders: z.array(z.string()).default([]), // every module folder on disk, in modules/ or grown/
  grown: z.array(z.string()).default([]), // the folders in grown/: what the builder can change or delete
});
export type ListReply = z.infer<typeof listReplySchema>;

/** rpc.build.remove: a module deleted. Its data is copied aside first and its code stays in git. */
export const removedSchema = replySchema.extend({
  name: z.string().optional(),
  version: z.string().nullable().default(null),
  data: z.string().nullable().default(null), // the copy of its data volume; null: it had none
  commit: z.string().nullable().default(null),
  tag: z.string().nullable().default(null), // <name>-v<version>-removed-<when> in grown/'s git: where its code is kept
});
export type Removed = z.infer<typeof removedSchema>;

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

/** One of a module's views: its block, or why it could not be shown. A block this app cannot read becomes that. */
export const moduleViewSchema = z
  .object({
    id: z.string(),
    title: z.string().default(""),
    request: z.string().default(""),
    block: z.unknown().optional(),
    error: z.string().nullable().default(null),
  })
  .transform(({ block, ...v }) => {
    if (block === null || block === undefined) return { ...v, block: null };
    const b = blockSchema.safeParse(block);
    return b.success ? { ...v, block: b.data } : { ...v, block: null, error: v.error ?? "this app cannot show this kind of view yet" };
  });
export type ModuleView = z.infer<typeof moduleViewSchema>;

/** GET /modules/{name}/views: what a module's page shows of its data. `declared`: the module's own views; else made
 *  from the replies of its requests that need nothing and only read. */
export const moduleViewsSchema = z.object({
  name: z.string(),
  running: z.boolean(),
  declared: z.boolean().default(false),
  views: z.array(moduleViewSchema).default([]),
});
export type ModuleViews = z.infer<typeof moduleViewsSchema>;
