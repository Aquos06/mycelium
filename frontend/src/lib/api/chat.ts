// What you say: a message for Main (sense.chat on channel web), an answer to an out.ask, a vote.

import { API, apiFetch } from "./client";
import { sentSchema, type Sent } from "@/lib/schemas";

export function sendChat(text: string, thread: string): Promise<Sent> {
  return apiFetch<Sent>(`${API}/chat`, {
    method: "POST",
    body: { text, thread },
    parse: { schema: sentSchema, what: "sending a message" },
    mock: async () => (await import("@/lib/mock")).mockSendChat(text, thread),
  });
}

export interface FeedbackFields {
  answer?: string;
  vote?: number;
}

export function sendFeedback(ref: string, thread: string, fields: FeedbackFields): Promise<Sent> {
  return apiFetch<Sent>(`${API}/chat/feedback`, {
    method: "POST",
    body: { ref, thread, ...fields },
    parse: { schema: sentSchema, what: "sending feedback" },
    mock: async () => (await import("@/lib/mock")).mockFeedback(ref, thread, fields),
  });
}
