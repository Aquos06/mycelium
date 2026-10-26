"use client";

// Chat: one thread with Main. Your messages, the plan it made, the reply or the question it asked back.
// Mounted with `key={thread}` by its page, so a new thread is a fresh component: no state to reset.
//
// The state lives in useConversation; every piece on screen is its own component in this folder:
// ChatHeader · Messages (UserBubble, TraceRow, AssistantMessage + Votes, AskCard) · Writing · Planning ·
// EmptyThread, and the Composer from ui.

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { threads } from "@/lib/chat";
import { ROUTES } from "@/lib/nav";
import { Composer } from "@/components/ui/Composer";
import { useThreads } from "@/components/ui/Sidebar";
import { ChatHeader } from "./ChatHeader";
import { EmptyThread } from "./EmptyThread";
import { Messages } from "./Messages";
import { Planning } from "./Planning";
import { Writing } from "./Writing";
import { useConversation } from "./useConversation";

export function Chat({ thread }: { thread: string }) {
  const router = useRouter();
  const list = useThreads();
  const { items, pendingId, live, votes, say, vote, answer } = useConversation(thread);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items.length, live?.text.length]);

  const title = list.find((t) => t.id === thread)?.title ?? (thread === "web" ? "Here" : thread);
  const busy = pendingId !== null;

  return (
    <>
      <ChatHeader title={title} onNew={() => router.push(ROUTES.chat(threads.fresh()))} />
      <div className="min-h-0 flex-1 overflow-y-auto" ref={scroller}>
        <div className="mx-auto flex max-w-[720px] flex-col gap-[22px] px-4 pt-6 pb-6 md:px-6 md:pt-9" aria-live="polite">
          {items.length === 0 && <EmptyThread />}
          <Messages items={items} votes={votes} onVote={vote} onAnswer={answer} />
          {busy && (live?.text ? <Writing text={live.text} /> : <Planning />)}
        </div>
      </div>
      <div className="px-4 pb-[18px] md:px-6">
        <Composer placeholder="Message mycelium, or log “coffee 85”" onSend={say} autoFocus className="mx-auto max-w-[720px]" />
      </div>
    </>
  );
}
