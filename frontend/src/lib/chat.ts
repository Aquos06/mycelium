// A conversation, assembled from the bus: what you said (sense.chat), what Main planned (trace.plan),
// what it said back (out.say) or asked (out.ask), and your answers (sense.feedback). Everything on
// channel "web" for one thread. The gateway only buffers the recent past, so each thread is also kept in
// localStorage and merged back in.

import { askSchema, planTraceSchema, saySchema, senseChatSchema, type BusEvent, type Json, type PlanTrace } from "@/lib/schemas";
import { readStored, writeStored } from "@/lib/storage";

export type ChatItem =
  | { kind: "user"; id: string; ts: string; text: string; pending?: boolean }
  | { kind: "assistant"; id: string; ts: string; text: string; cause: string | null }
  | {
      kind: "ask";
      id: string;
      ts: string;
      text: string;
      choices: string[];
      ref: string;
      cause: string | null;
      answered: string | null;
    }
  | { kind: "trace"; id: string; ts: string; cause: string | null; trace: PlanTrace };

export interface Thread {
  id: string;
  title: string;
  ts: string; // last activity
}

export const CHANNEL = "web";
export const DEFAULT_THREAD = "web";
export const THREADS_KEY = "mycelium.threads";
const MAX_STORED = 400;
const NO_THREADS: Thread[] = [];

export const byRecent = (a: Thread, b: Thread) => (a.ts < b.ts ? 1 : -1);

export const threads = {
  all: (): Thread[] => readStored<Thread[]>(THREADS_KEY, NO_THREADS).slice().sort(byRecent),
  touch(id: string, firstText: string): Thread[] {
    const list = readStored<Thread[]>(THREADS_KEY, NO_THREADS).map((t) => ({ ...t }));
    const now = new Date().toISOString();
    const existing = list.find((t) => t.id === id);
    if (existing) existing.ts = now;
    else list.push({ id, title: firstText.replace(/\s+/g, " ").slice(0, 60), ts: now });
    const sorted = list.sort(byRecent).slice(0, 30);
    writeStored(THREADS_KEY, sorted);
    return sorted;
  },
  fresh: (): string => `web-${Date.now().toString(36)}`,
};

export const stored = {
  key: (thread: string) => `mycelium.chat.${thread}`,
  load: (thread: string): ChatItem[] => readStored<ChatItem[]>(stored.key(thread), NO_ITEMS),
  save: (thread: string, items: ChatItem[]) =>
    writeStored(
      stored.key(thread),
      items.filter((i) => !(i.kind === "user" && i.pending)).slice(-MAX_STORED),
    ),
};
const NO_ITEMS: ChatItem[] = [];

const onThread = (d: Json, thread: string) => d.channel === CHANNEL && String(d.thread) === thread;

/** The items the bus holds for `thread`, in conversation order (a turn: you, the plan, the reply). */
export function fromEvents(events: BusEvent[], thread: string): ChatItem[] {
  const items: ChatItem[] = [];
  const answers = new Map<string, string>(); // ask ref -> answer
  for (const e of events) {
    const d = e.data;
    if (!onThread(d, thread)) continue;
    switch (e.subject) {
      case "sense.chat": {
        const m = senseChatSchema.safeParse(d);
        if (m.success && m.data.text) items.push({ kind: "user", id: m.data.id, ts: m.data.ts ?? e.received, text: m.data.text });
        break;
      }
      case "sense.feedback":
        if (typeof d.answer === "string" && d.ref) answers.set(String(d.ref), d.answer);
        break;
      case "out.say": {
        const m = saySchema.safeParse(d);
        if (m.success) items.push({ kind: "assistant", id: m.data.id, ts: m.data.ts ?? e.received, text: m.data.text, cause: m.data.cause });
        break;
      }
      case "out.ask": {
        const m = askSchema.safeParse(d);
        if (m.success)
          items.push({
            kind: "ask",
            id: m.data.id,
            ts: m.data.ts ?? e.received,
            text: m.data.text,
            choices: m.data.choices,
            ref: m.data.ref ?? m.data.id,
            cause: m.data.cause,
            answered: null,
          });
        break;
      }
      case "trace.plan": {
        const m = planTraceSchema.safeParse(d);
        if (m.success) items.push({ kind: "trace", id: m.data.id, ts: m.data.ts ?? e.received, cause: m.data.cause, trace: m.data });
        break;
      }
    }
  }
  for (const i of items) if (i.kind === "ask" && answers.has(i.ref)) i.answered = answers.get(i.ref)!;
  return order(items);
}

/** Stored items and bus items as one list, by id; the newest version of an item wins (an ask gets answered). */
export function merge(a: ChatItem[], b: ChatItem[]): ChatItem[] {
  const byId = new Map<string, ChatItem>();
  for (const i of [...a, ...b]) {
    const prev = byId.get(i.id);
    byId.set(i.id, prev && prev.kind === "ask" && i.kind === "ask" ? { ...i, answered: i.answered ?? prev.answered } : i);
  }
  return order([...byId.values()]);
}

const RANK: Record<ChatItem["kind"], number> = { user: 0, trace: 1, assistant: 2, ask: 2 };

/** Conversation order: chronological, with a turn's plan and reply kept right after the message they answer. */
export function order(items: ChatItem[]): ChatItem[] {
  const chrono = items.slice().sort((x, y) => (x.ts < y.ts ? -1 : x.ts > y.ts ? 1 : 0));
  const anchor = new Map<string, number>();
  chrono.forEach((i, idx) => {
    if (i.kind === "user") anchor.set(i.id, idx);
  });
  const keyed = chrono.map((i, idx) => {
    const cause = i.kind === "user" ? null : i.cause;
    const at = cause !== null && anchor.has(cause) ? anchor.get(cause)! : idx;
    return { i, at, rank: RANK[i.kind], idx };
  });
  keyed.sort((x, y) => x.at - y.at || x.rank - y.rank || x.idx - y.idx);
  return keyed.map((k) => k.i);
}

/** The id of your last message when Main has not planned or replied to it yet (and it is fresh), else null.
 *  That id is the `cause` a reply being written streams under. */
export function pendingTurn(items: ChatItem[], now = Date.now()): string | null {
  const last = items[items.length - 1];
  if (!last || last.kind !== "user" || last.pending) return null;
  return now - new Date(last.ts).getTime() < 180_000 ? last.id : null;
}

/** True when the last thing in the thread is you, and Main has not planned or replied yet. */
export function waiting(items: ChatItem[], now = Date.now()): boolean {
  return pendingTurn(items, now) !== null;
}
