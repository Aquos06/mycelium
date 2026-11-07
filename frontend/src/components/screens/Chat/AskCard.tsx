"use client";

// A question Main asked, its text as markdown (a proposal card lists what the module will do) and what it showed
// from a module, with its choices as buttons; once answered, the answer with a tick.

import { Check } from "lucide-react";
import { Blocks } from "@/components/ui/blocks";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import type { Block } from "@/lib/schemas";

export function AskCard({
  text,
  choices,
  answered,
  onAnswer,
  blocks,
}: {
  text: string;
  blocks?: Block[];
  choices: string[];
  answered: string | null;
  onAnswer: (choice: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-card border border-line-strong bg-surface shadow-card md:ml-[38px]" role="group" aria-label={text} data-kind="ask">
      <Markdown text={text} className="px-4 py-3.5 text-[15px] leading-normal text-pretty" />
      <Blocks blocks={blocks} className="px-4 pb-3.5" />
      <div className="flex flex-wrap items-center gap-1.5 border-t border-sunken bg-paper px-3 py-2.5">
        {answered ? (
          <span className="flex items-center gap-1.5 text-[12.5px] text-moss">
            <Check className="size-[13px]" strokeWidth={2.5} /> {answered}
          </span>
        ) : (
          choices.map((c) => (
            <Button key={c} variant="primary" onClick={() => onAnswer(c)}>
              {c}
            </Button>
          ))
        )}
      </div>
    </div>
  );
}
