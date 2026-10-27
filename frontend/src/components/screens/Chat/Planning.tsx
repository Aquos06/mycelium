"use client";

// Between your message and the first piece of the reply: Main is recalling and planning.

import { Spinner } from "@/components/ui/Primitives";

export function Planning() {
  return (
    <div className="flex items-center gap-2.5 text-[13px] text-ink3 md:ml-[38px]" role="status">
      <Spinner ink /> Planning…
    </div>
  );
}
