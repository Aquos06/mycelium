"use client";

// Chat: one thread with Main. Your messages, the plan it made, the reply or the question it asked back.
// Mounted with `key={thread}` by its page, so a new thread is a fresh component: no state to reset.

import { Mic, ThumbsDown, ThumbsUp } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useBus } from "@/lib/bus";
import { fromEvents, merge, stored, threads, waiting, type ChatItem } from "@/lib/chat";
import { useMounted, useNow, useStored } from "@/lib/hooks";
import { ROUTES } from "@/lib/nav";
import { useFeedback, useSendChat } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Composer } from "@/components/ui/Composer";
import { Logo } from "@/components/ui/Logo";
import { Empty, Spinner } from "@/components/ui/Primitives";
import { useThreads } from "@/components/ui/Sidebar";
import { Crumb, Right, Sep, Title, Topbar } from "@/components/ui/Topbar";
import { AskCard } from "./AskCard";
import { TraceRow } from "./TraceRow";

const NO_ITEMS: ChatItem[] = [];
const NO_VOTES: Record<string, number> = {};

export function Chat({ thread }: { thread: string }) {
  const router = useRouter();
  const { events } = useBus();
  const send = useSendChat();
  const feedback = useFeedback();
  const mounted = useMounted();
  const now = useNow();
  const [pending, setPending] = useState<ChatItem[]>([]);
  const [kept] = useStored<ChatItem[]>(stored.key(thread), NO_ITEMS);
  const [votes, setVotes] = useStored<Record<string, number>>("mycelium.votes", NO_VOTES);
  const list = useThreads();
  const scroller = useRef<HTMLDivElement>(null);

  const items = useMemo(() => {
    const all = merge(kept, fromEvents(events, thread));
    const seen = new Set(all.map((i) => i.id));
    return [...all, ...pending.filter((p) => !seen.has(p.id))];
  }, [events, thread, pending, kept]);

  // What the bus holds is kept for next time; the write is skipped when nothing changed (lib/storage).
  useEffect(() => {
    if (mounted && items.length) stored.save(thread, items);
  }, [items, thread, mounted]);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items.length]);

  const title = list.find((t) => t.id === thread)?.title ?? (thread === "web" ? "Here" : thread);

  const say = async (text: string) => {
    const r = await send.mutateAsync({ text, thread });
    threads.touch(thread, text);
    setPending((p) => [...p, { kind: "user", id: r.id, ts: new Date().toISOString(), text, pending: true }]);
  };

  const vote = (id: string, v: number) => {
    const next = { ...votes, [id]: votes[id] === v ? 0 : v };
    setVotes(next);
    if (next[id] !== 0) feedback.mutate({ ref: id, thread, vote: next[id] });
  };

  const busy = now !== null && waiting(items, now);

  return (
    <>
      <Topbar className="px-4">
        <Crumb>Chat</Crumb>
        <Sep />
        <Title className="max-w-[360px] truncate">{title}</Title>
        <Right>
          <Button size="sm" onClick={() => router.push(ROUTES.chat(threads.fresh()))}>
            New chat
          </Button>
          <ButtonLink variant="moss" href={ROUTES.voice}>
            <Mic className="size-3.5" /> Switch to voice
          </ButtonLink>
        </Right>
      </Topbar>
      <div className="min-h-0 flex-1 overflow-y-auto" ref={scroller}>
        <div className="mx-auto flex max-w-[720px] flex-col gap-[22px] px-4 pt-6 pb-6 md:px-6 md:pt-9" aria-live="polite">
          {items.length === 0 && (
            <Empty className="py-10 text-center">
              Say something. Main recalls what it knows about it, plans, and answers; the plan shows under each reply.
            </Empty>
          )}
          {items.map((m) => {
            switch (m.kind) {
              case "user":
                return (
                  <div key={m.id} className="flex justify-end" data-kind="user">
                    <div className={cn("max-w-[75%] rounded-[18px] bg-sunken px-[15px] py-[9px] text-[15px] wrap-break-word whitespace-pre-wrap text-pretty", m.pending && "text-ink2")}>
                      {m.text}
                    </div>
                  </div>
                );
              case "trace":
                return <TraceRow key={m.id} t={m.trace} />;
              case "assistant":
                return (
                  <div key={m.id} className="group flex gap-3.5" data-kind="assistant">
                    <div className="mt-0.5 flex size-6 shrink-0">
                      <Logo />
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col gap-2.5 text-[15px] leading-relaxed text-pretty">
                      {m.text.split(/\n{2,}/).map((p, i) => (
                        <p key={i} className="m-0 wrap-break-word whitespace-pre-wrap">
                          {p}
                        </p>
                      ))}
                      <div className={cn("flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100", votes[m.id] && "opacity-100")}>
                        <VoteButton on={votes[m.id] === 1} title="Good answer" onClick={() => vote(m.id, 1)}>
                          <ThumbsUp className="size-3.5" />
                        </VoteButton>
                        <VoteButton on={votes[m.id] === -1} title="Bad answer" onClick={() => vote(m.id, -1)}>
                          <ThumbsDown className="size-3.5" />
                        </VoteButton>
                      </div>
                    </div>
                  </div>
                );
              case "ask":
                return (
                  <AskCard key={m.id} text={m.text} answered={m.answered} choices={m.choices} onAnswer={(c) => feedback.mutate({ ref: m.ref, thread, answer: c })} />
                );
            }
          })}
          {busy && (
            <div className="flex items-center gap-2.5 text-[13px] text-ink3 md:ml-[38px]" role="status">
              <Spinner ink /> Planning…
            </div>
          )}
        </div>
      </div>
      <div className="px-4 pb-[18px] md:px-6">
        <Composer placeholder="Message mycelium, or log “coffee 85”" onSend={say} autoFocus className="mx-auto max-w-[720px]" />
      </div>
    </>
  );
}

function VoteButton({ on, title, onClick, children }: { on: boolean; title: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      aria-pressed={on}
      className={cn("inline-flex size-[26px] items-center justify-center rounded-[7px] text-ink3 hover:bg-sunken hover:text-ink", on && "text-moss")}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
