"use client";

// The bus in the browser: one websocket to the web gateway, the recent events as React state, and the
// replies being written right now.
//
// On connect the gateway says hello with its last seq; the page then fetches /events for what it missed
// and takes every new frame from the socket. A gateway restart resets the seq counter, so events are
// keyed by (received, seq) and the cursor starts over when hello's seq is behind ours.
//
// Stream frames are different: a piece of a reply as the model writes it, keyed by the message it answers
// (`cause`). They are never numbered or kept by the gateway, so a reconnect simply waits for the reply.
//
// In MOCK mode the socket is a timer (lib/mock): the only module outside lib/api allowed to import it.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, MOCK, fetchEvents, socketProtocols, socketUrl, unauthorized } from "@/lib/api";
import { frameSchema, type BusEvent, type StreamDelta } from "@/lib/schemas";

/** refused: the gateway does not serve this page's origin (WEB_CORS_ORIGINS); reconnecting cannot fix it. */
export type BusStatus = "connecting" | "live" | "offline" | "unauthorized" | "refused";

/** A reply being written: the text so far of the model call that is running for one message. */
export interface StreamText {
  request: string;
  provider: string;
  text: string;
  done: boolean;
}

export interface BusState {
  events: BusEvent[]; // oldest first
  streams: Record<string, StreamText>; // by cause: the id of the message being answered
  status: BusStatus;
  name: string; // WEB_USER_NAME, from hello
  retry: () => void;
}

export const MAX_EVENTS = 1500;
export const WS_UNAUTHORIZED = 4401;
export const WS_FORBIDDEN = 4403;

/** Exported for tests, which render a screen inside a provider holding a fixed value. */
export const BusContext = createContext<BusState | null>(null);

const key = (e: BusEvent) => `${e.received}|${e.seq}`;

/** Incoming events merged into the list: by key, oldest first, the last MAX_EVENTS kept. */
export function mergeEvents(prev: BusEvent[], incoming: BusEvent[]): BusEvent[] {
  if (!incoming.length) return prev;
  const byKey = new Map(prev.map((e) => [key(e), e]));
  for (const e of incoming) byKey.set(key(e), e);
  const all = [...byKey.values()].sort((a, b) =>
    a.received < b.received ? -1 : a.received > b.received ? 1 : a.seq - b.seq,
  );
  return all.length > MAX_EVENTS ? all.slice(-MAX_EVENTS) : all;
}

/** One stream frame folded in. A new `request` for the same cause (the next planner round) starts over:
 *  the text of a round that ended in tool calls is not the reply. */
export function applyStream(prev: Record<string, StreamText>, d: StreamDelta): Record<string, StreamText> {
  const cur = prev[d.cause];
  const next: StreamText =
    cur && cur.request === d.request
      ? { ...cur, text: cur.text + d.text, done: d.done }
      : { request: d.request, provider: d.provider, text: d.text, done: d.done };
  return { ...prev, [d.cause]: next };
}

/** The reply landed (out.say / out.ask with that cause): its stream is finished with. */
export function dropStreams(prev: Record<string, StreamText>, events: BusEvent[]): Record<string, StreamText> {
  let out = prev;
  for (const e of events) {
    if ((e.subject === "out.say" || e.subject === "out.ask") && typeof e.data.cause === "string" && e.data.cause in out) {
      if (out === prev) out = { ...prev };
      delete out[e.data.cause];
    }
  }
  return out;
}

export function BusProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<BusEvent[]>([]);
  const [streams, setStreams] = useState<Record<string, StreamText>>({});
  const [status, setStatus] = useState<BusStatus>("connecting");
  const [name, setName] = useState("");
  const [attempt, setAttempt] = useState(0);
  const cursor = useRef(0);

  const merge = useCallback((incoming: BusEvent[]) => {
    setEvents((prev) => mergeEvents(prev, incoming));
    setStreams((prev) => dropStreams(prev, incoming));
  }, []);
  const stream = useCallback((d: StreamDelta) => setStreams((prev) => applyStream(prev, d)), []);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;
    let failures = 0;
    let unsubscribe: (() => void) | null = null;

    const fill = async () => {
      try {
        const r = await fetchEvents(cursor.current, 300);
        merge(r.events);
        for (const e of r.events) cursor.current = Math.max(cursor.current, e.seq);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) setStatus("unauthorized");
      }
    };

    const connectMock = async () => {
      const mock = await import("@/lib/mock");
      if (closed) return;
      if (!mock.mockAuthorized()) {
        setStatus("unauthorized");
        unauthorized();
        return;
      }
      setName(mock.MOCK_NAME);
      merge(mock.mockBus.all());
      const offEvents = mock.mockBus.subscribe((e) => merge([e]));
      const offStream = mock.mockBus.subscribeStream(stream);
      unsubscribe = () => {
        offEvents();
        offStream();
      };
      setStatus("live");
    };

    const connect = () => {
      if (closed) return;
      setStatus((s) => (s === "unauthorized" ? s : "connecting"));
      socket = new WebSocket(socketUrl(), socketProtocols());
      socket.onmessage = (m) => {
        const parsed = frameSchema.safeParse(JSON.parse(m.data as string));
        if (!parsed.success) return;
        const frame = parsed.data;
        if (frame.type === "hello") {
          failures = 0;
          setName(frame.name);
          setStatus("live");
          if (frame.seq < cursor.current) cursor.current = 0; // the gateway restarted: its counter is young again
          void fill();
        } else if (frame.type === "stream") {
          stream(frame.data);
        } else {
          const ev: BusEvent = { seq: frame.seq, subject: frame.subject, data: frame.data, received: frame.received };
          cursor.current = Math.max(cursor.current, ev.seq);
          merge([ev]);
        }
      };
      socket.onclose = (e) => {
        socket = null;
        if (closed) return;
        if (e.code === WS_UNAUTHORIZED) {
          setStatus("unauthorized");
          unauthorized();
          return;
        }
        if (e.code === WS_FORBIDDEN) {
          setStatus("refused");
          return;
        }
        setStatus("offline");
        failures += 1;
        timer = window.setTimeout(connect, Math.min(10_000, 1000 * failures));
      };
      socket.onerror = () => socket?.close();
    };

    if (MOCK) void connectMock();
    else connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      socket?.close();
      unsubscribe?.();
    };
  }, [attempt, merge, stream]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const value = useMemo(() => ({ events, streams, status, name, retry }), [events, streams, status, name, retry]);
  return <BusContext.Provider value={value}>{children}</BusContext.Provider>;
}

export function useBus(): BusState {
  const v = useContext(BusContext);
  if (!v) throw new Error("useBus outside BusProvider");
  return v;
}

/** The events whose subject matches `prefix` (a NATS-style prefix such as "mod.hello." or "out."). */
export function useEvents(prefix: string | ((e: BusEvent) => boolean)): BusEvent[] {
  const { events } = useBus();
  return useMemo(
    () => events.filter(typeof prefix === "string" ? (e) => e.subject.startsWith(prefix) : prefix),
    [events, prefix],
  );
}
