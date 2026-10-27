"use client";

// The reply being written: the text so far from stream.llm, with a caret. Replaced by the reply itself.

import { Logo } from "@/components/ui/Logo";

export function Writing({ text }: { text: string }) {
  return (
    <div className="flex gap-3.5" data-kind="stream" role="status" aria-label="Main is writing">
      <div className="mt-0.5 flex size-6 shrink-0">
        <Logo />
      </div>
      <div className="min-w-0 flex-1 text-[15px] leading-relaxed wrap-break-word whitespace-pre-wrap text-pretty text-ink1">
        {text}
        <span className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] animate-pulse-soft bg-moss" aria-hidden="true" />
      </div>
    </div>
  );
}
