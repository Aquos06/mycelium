// The system domain: the gateway about itself. Mirrors services/web/system/schemas.py.

import { z } from "zod";

export const healthSchema = z.object({
  ok: z.literal(true),
  name: z.string(),
  channel: z.string(),
  version: z.string(),
  events: z.number().int(),
  clients: z.number().int(),
  auth: z.boolean(),
});
export type Health = z.infer<typeof healthSchema>;
