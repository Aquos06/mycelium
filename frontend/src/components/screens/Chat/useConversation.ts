"use client";

// The state of one thread: what the bus holds for it, what this browser kept from before, what you just
// sent and the bus has not echoed yet, the reply being written, your votes. The screen only renders it.

import { useEffect, useMemo, useState } from "react";
import { useBus, type StreamText } from "@/lib/bus";
import { fromEvents, merge, pendingTurn, stored, threads, type ChatItem } from "@/lib/chat";
import { useMounted, useNow, useStored } from "@/lib/hooks";
import { useFeedback, useSendChat } from "@/lib/queries";

const NO_ITEMS: ChatItem[] = [];
const NO_VOTES: Record<string, number> = {};

export interface Conversation {
  items: ChatItem[];
  /** The id of your last message while Main is still on it, else null. */
  pendingId: string | null;
  /** The reply being written for that message, once the first piece has arrived. */
  live: StreamText | undefined;
  votes: Record<string, number>;
  say: (text: string) => Promise<void>;
  vote: (id: string, value: number) => void;
  answer: (ref: string, choice: string) => void;
}

export function useConversation(thread: string): Conversation {
  const { events, streams } = useBus();
  const send = useSendChat();
  const feedback = useFeedback();
  const mounted = useMounted();
  const now = useNow();
  const [pending, setPending] = useState<ChatItem[]>([]);
  const [kept] = useStored<ChatItem[]>(stored.key(thread), NO_ITEMS);
  const [votes, setVotes] = useStored<Record<string, number>>("mycelium.votes", NO_VOTES);

  const items = useMemo(() => {
    const all = merge(kept, fromEvents(events, thread));
    const seen = new Set(all.map((i) => i.id));
    return [...all, ...pending.filter((p) => !seen.has(p.id))];
  }, [events, thread, pending, kept]);

  // What the bus holds is kept for next time; the write is skipped when nothing changed (lib/storage).
  useEffect(() => {
    if (mounted && items.length) stored.save(thread, items);
  }, [items, thread, mounted]);

  const pendingId = now === null ? null : pendingTurn(items, now);
  const live = pendingId ? streams[pendingId] : undefined;

  const say = async (text: string) => {
    const r = await send.mutateAsync({ text, thread });
    threads.touch(thread, text);
    setPending((p) => [...p, { kind: "user", id: r.id, ts: new Date().toISOString(), text, pending: true }]);
  };

  const vote = (id: string, value: number) => {
    const next = { ...votes, [id]: votes[id] === value ? 0 : value };
    setVotes(next);
    if (next[id] !== 0) feedback.mutate({ ref: id, thread, vote: next[id] });
  };

  const answer = (ref: string, choice: string) => feedback.mutate({ ref, thread, answer: choice });

  return { items, pendingId, live, votes, say, vote, answer };
}
