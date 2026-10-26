"use client";

// What you said, on the right. Grey while the bus has not echoed it back yet.

import { cn } from "@/lib/utils";

export function UserBubble({ text, pending = false }: { text: string; pending?: boolean }) {
  return (
    <div className="flex justify-end" data-kind="user">
      <div
        className={cn(
          "max-w-[75%] rounded-[18px] bg-sunken px-[15px] py-[9px] text-[15px] wrap-break-word whitespace-pre-wrap text-pretty",
          pending && "text-ink2",
        )}
      >
        {text}
      </div>
    </div>
  );
}
