"use client";

// A thread with nothing in it yet.

import { Empty } from "@/components/ui/Primitives";

export function EmptyThread() {
  return (
    <Empty className="py-10 text-center">
      Say something. Main recalls what it knows about it, plans, and answers; the plan shows under each reply.
    </Empty>
  );
}
