"use client";

// Thumbs on a reply. Shown on hover, kept visible once you voted; a vote goes out as sense.feedback.

import { ThumbsDown, ThumbsUp } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Votes({ value, onVote }: { value: number | undefined; onVote: (v: number) => void }) {
  return (
    <div className={cn("flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100", value && "opacity-100")}>
      <VoteButton on={value === 1} title="Good answer" onClick={() => onVote(1)}>
        <ThumbsUp className="size-3.5" />
      </VoteButton>
      <VoteButton on={value === -1} title="Bad answer" onClick={() => onVote(-1)}>
        <ThumbsDown className="size-3.5" />
      </VoteButton>
    </div>
  );
}

function VoteButton({ on, title, onClick, children }: { on: boolean; title: string; onClick: () => void; children: ReactNode }) {
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
