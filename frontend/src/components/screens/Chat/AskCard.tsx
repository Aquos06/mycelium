"use client";

// A question Main asked, with its choices as buttons; once answered, the answer with a tick.

import { Check } from "lucide-react";
import { Button } from "@/components/ui/Button";

export function AskCard({
  text,
  choices,
  answered,
  onAnswer,
}: {
  text: string;
  choices: string[];
  answered: string | null;
  onAnswer: (choice: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-card border border-line-strong bg-surface shadow-card md:ml-[38px]" role="group" aria-label={text} data-kind="ask">
      <div className="px-4 py-3.5 text-[15px] leading-normal text-pretty">{text}</div>
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
