"use client";

// Main's reply: the mark, the text as markdown, the thumbs.

import { Logo } from "@/components/ui/Logo";
import { Markdown } from "@/components/ui/Markdown";
import { Votes } from "./Votes";

export function AssistantMessage({ text, vote, onVote }: { text: string; vote: number | undefined; onVote: (v: number) => void }) {
  return (
    <div className="group flex gap-3.5" data-kind="assistant">
      <div className="mt-0.5 flex size-6 shrink-0">
        <Logo />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2.5 text-[15px] leading-relaxed text-pretty">
        <Markdown text={text} />
        <Votes value={vote} onVote={onVote} />
      </div>
    </div>
  );
}
