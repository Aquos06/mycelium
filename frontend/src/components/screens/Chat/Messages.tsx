"use client";

// The thread's items, each as its own piece: your bubble, the plan row, Main's reply, a question.

import type { ChatItem } from "@/lib/chat";
import { AskCard } from "./AskCard";
import { AssistantMessage } from "./AssistantMessage";
import { TraceRow } from "./TraceRow";
import { UserBubble } from "./UserBubble";

export function Messages({
  items,
  votes,
  onVote,
  onAnswer,
}: {
  items: ChatItem[];
  votes: Record<string, number>;
  onVote: (id: string, value: number) => void;
  onAnswer: (ref: string, choice: string) => void;
}) {
  return (
    <>
      {items.map((m) => {
        switch (m.kind) {
          case "user":
            return <UserBubble key={m.id} text={m.text} pending={m.pending} />;
          case "trace":
            return <TraceRow key={m.id} t={m.trace} />;
          case "assistant":
            return <AssistantMessage key={m.id} text={m.text} vote={votes[m.id]} onVote={(v) => onVote(m.id, v)} />;
          case "ask":
            return <AskCard key={m.id} text={m.text} answered={m.answered} choices={m.choices} onAnswer={(c) => onAnswer(m.ref, c)} />;
        }
      })}
    </>
  );
}
