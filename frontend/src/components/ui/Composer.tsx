"use client";

// The one place you type: Enter sends, Shift+Enter breaks the line, the box grows with the text.

import { ArrowUp, Mic } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button, ButtonLink } from "./Button";
import { Kbd } from "./Primitives";
import { ROUTES } from "@/lib/nav";
import { cn } from "@/lib/utils";

interface Props {
  placeholder: string;
  onSend: (text: string) => Promise<void> | void;
  initial?: string;
  autoFocus?: boolean;
  talkLabel?: boolean; // the home variant: a labelled Talk button
  className?: string;
}

export function Composer({ placeholder, onSend, initial = "", autoFocus = false, talkLabel = false, className }: Props) {
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(200, el.scrollHeight)}px`;
  }, [text]);

  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSend(t);
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      ref.current?.focus();
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  };

  const ready = text.trim().length > 0 && !busy;
  return (
    <div className={cn("flex flex-col gap-2 rounded-composer border border-line-strong bg-surface py-2.5 pr-3 pl-[18px] text-left shadow-raised", className)}>
      <textarea
        ref={ref}
        rows={1}
        value={text}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        aria-label="Message"
        className="max-h-[200px] min-h-6 w-full resize-none border-none bg-transparent p-0 text-[15px] leading-normal text-ink outline-none placeholder:text-ink3"
      />
      <div className="flex items-center gap-1">
        <span className="flex h-[30px] items-center gap-1.5 px-2.5 text-[12.5px] text-ink3">
          {error ? (
            <span role="alert" className="text-red-text">
              {error}
            </span>
          ) : (
            <>
              <Kbd>↵</Kbd> send · <Kbd>⇧↵</Kbd> newline
            </>
          )}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {talkLabel ? (
            <ButtonLink variant="moss" href={ROUTES.voice} title="Talk (⌘J)">
              <Mic className="size-[15px]" /> Talk
            </ButtonLink>
          ) : (
            <ButtonLink variant="round-moss" size="none" href={ROUTES.voice} title="Voice (⌘J)" aria-label="Voice">
              <Mic className="size-[15px]" />
            </ButtonLink>
          )}
          <Button variant="round" size="none" data-ready={ready} onClick={() => void send()} disabled={!ready} title="Send" aria-label="Send">
            <ArrowUp className="size-4" strokeWidth={2.25} />
          </Button>
        </div>
      </div>
    </div>
  );
}
