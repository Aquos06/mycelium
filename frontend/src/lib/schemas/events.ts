// The events domain: one bus event as the gateway sends it, the page of recent ones, the socket frames.
// Mirrors services/web/events/schemas.py.

import { z } from "zod";
import { jsonSchema } from "./vocabulary";

export const busEventSchema = z.object({
  seq: z.number().int(),
  subject: z.string(),
  data: jsonSchema,
  received: z.string(),
});
export type BusEvent = z.infer<typeof busEventSchema>;

export const eventsPageSchema = z.object({
  ok: z.literal(true),
  seq: z.number().int(),
  events: z.array(busEventSchema),
});
export type EventsPage = z.infer<typeof eventsPageSchema>;

export const helloFrameSchema = z.object({
  type: z.literal("hello"),
  seq: z.number().int(),
  name: z.string(),
});

export const eventFrameSchema = z.object({
  type: z.literal("event"),
  seq: z.number().int(),
  subject: z.string(),
  data: jsonSchema,
  received: z.string(),
});

/** A piece of a reply as the model writes it (services/gateway/schemas/completion.py::StreamDelta). */
export const streamDeltaSchema = z.looseObject({
  cause: z.string(),
  request: z.string(),
  slot: z.string().default("planner"),
  provider: z.string().default(""),
  seq: z.number().int(),
  text: z.string().default(""),
  done: z.boolean().default(false),
});
export type StreamDelta = z.infer<typeof streamDeltaSchema>;

/** Live, never numbered, never kept: the gateway forwards stream.* as it comes. */
export const streamFrameSchema = z.object({
  type: z.literal("stream"),
  subject: z.string(),
  data: streamDeltaSchema,
});

export const frameSchema = z.discriminatedUnion("type", [helloFrameSchema, eventFrameSchema, streamFrameSchema]);
export type Frame = z.infer<typeof frameSchema>;
