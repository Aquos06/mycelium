"use client";

// A reasoning model's thinking as it comes: most of the wait before the first word. While Main thinks, the
// latest lines show under a spinner; once the reply is being written they fold into one line you can open.
// Keyed by the model call, so the next planner round starts folded again.
//
// Only "Thinking…" is announced: the text itself sits outside the live region, or a screen reader would read
// all of it again with every frame.

import { useEffect, useRef, useState } from "react";
import { Spinner } from "@/components/ui/Primitives";

export function Thinking({ text, writing }: { text: string; writing: boolean }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const shown = !writing || open;

  useEffect(() => {
    const el = box.current;
    if (el && !writing) el.scrollTop = el.scrollHeight; // follow the newest line
  }, [text, writing]);

  return (
    <div className="flex flex-col gap-1.5 md:ml-[38px]" data-kind="thinking">
      {writing ? (
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="self-start text-[13px] text-ink3 hover:text-ink2">
          {open ? "Hide thinking" : "Show thinking"}
        </button>
      ) : (
        <div className="flex items-center gap-2.5 text-[13px] text-ink3" role="status" aria-label="Main is thinking">
          <Spinner ink /> Thinking…
        </div>
      )}
      {shown && (
        <div ref={box} aria-live="off" className="max-h-32 overflow-y-auto border-l-2 border-line pl-3 text-[13px] leading-relaxed wrap-break-word whitespace-pre-wrap text-ink3">
          {text}
        </div>
      )}
    </div>
  );
}
