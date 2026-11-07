"use client";

// Main's reply: the mark, the text as markdown, what it showed from a module (a table, a chart, ...), the thumbs.

import { Blocks } from "@/components/ui/blocks";
import { Logo } from "@/components/ui/Logo";
import { Markdown } from "@/components/ui/Markdown";
import type { Block } from "@/lib/schemas";
import { Votes } from "./Votes";

export function AssistantMessage({
  text,
  blocks,
  vote,
  onVote,
}: {
  text: string;
  blocks?: Block[];
  vote: number | undefined;
  onVote: (v: number) => void;
}) {
  return (
    <div className="group flex gap-3.5" data-kind="assistant">
      <div className="mt-0.5 flex size-6 shrink-0">
        <Logo />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2.5 text-[15px] leading-relaxed text-pretty">
        <Markdown text={text} />
        <Blocks blocks={blocks} className="mt-1" />
        <Votes value={vote} onVote={onVote} />
      </div>
    </div>
  );
}
