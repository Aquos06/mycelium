"use client";

// The reply being written: the text so far from stream.llm, as markdown with its open marks closed and a caret
// after the last word. Replaced by the reply itself.

import { Logo } from "@/components/ui/Logo";
import { Markdown } from "@/components/ui/Markdown";

export function Writing({ text }: { text: string }) {
  return (
    <div className="flex gap-3.5" data-kind="stream" role="status" aria-label="Main is writing">
      <div className="mt-0.5 flex size-6 shrink-0">
        <Logo />
      </div>
      <Markdown text={text} streaming className="flex-1 text-[15px] leading-relaxed text-pretty text-ink1" />
    </div>
  );
}
