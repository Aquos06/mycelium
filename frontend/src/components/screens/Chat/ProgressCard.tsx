"use client";

// A job Main follows for you, as one card that changes in place: a build's rounds (each with why it failed or
// that it passed), the step it is on with how long it has taken, and the steps still to come. From out.progress.
//
// Only the steps are read out as they change: the running clock is hidden from screen readers, or the chat's
// live region would announce it every tick. Only a step under way has a clock, so a finished card never
// re-renders on the tick.
//
// A running card that has heard nothing for a while asks the builder how the build stands: if it ended while the
// app was shut, its last update may have left the gateway's buffer, and the card would spin for good.

import { Check, Circle, X } from "lucide-react";
import { jobOf, settle, updatedAt, type ProgressItem } from "@/lib/chat";
import { took } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useBuild } from "@/lib/queries";
import type { ProgressStep } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/Primitives";

/** No update for this long, and a running card asks the builder (a step can take minutes: verify builds an image). */
export const QUIET_MS = 5 * 60_000;

type State = ProgressItem["state"];

function Mark({ state }: { state: ProgressStep["state"] | State }) {
  if (state === "done") return <Check className="size-3.5 text-moss" strokeWidth={2.5} aria-hidden="true" />;
  if (state === "failed") return <X className="size-3.5 text-red" strokeWidth={2.5} aria-hidden="true" />;
  if (state === "active" || state === "running") return <Spinner ink />;
  return <Circle className="size-2.5 text-ink4" strokeWidth={2.5} aria-hidden="true" />;
}

const SAID: Record<ProgressStep["state"], string> = { done: "done", failed: "failed", active: "now", pending: "to come" };

export function ProgressCard({ item }: { item: ProgressItem }) {
  return item.state === "running" ? <Running item={item} /> : <Card item={item} />;
}

/** A card still under way: as it is, or as the builder says it ended once it has been quiet for QUIET_MS. */
function Running({ item }: { item: ProgressItem }) {
  const now = useNow();
  const quiet = now !== null && now - new Date(updatedAt(item)).getTime() > QUIET_MS;
  const build = useBuild(jobOf(item), quiet);
  return <Card item={build.data ? settle(item, build.data) : item} />;
}

function Card({ item: { title, state, steps, note } }: { item: ProgressItem }) {
  return (
    <div className="overflow-hidden rounded-card border border-line-strong bg-surface shadow-card md:ml-[38px]" role="group" aria-label={title} data-kind="progress" data-state={state}>
      <div className="flex items-center gap-2.5 border-b border-sunken px-4 py-3">
        <span className="flex size-4 items-center justify-center">
          <Mark state={state} />
        </span>
        <span className={cn("text-[14.5px] font-medium", state === "failed" && "text-red-text")}>{title}</span>
      </div>
      <ol className="m-0 flex list-none flex-col gap-2 px-4 py-3">
        {steps.map((s, i) => (
          <li key={i} className="flex gap-2.5 text-[13.5px] leading-snug" data-state={s.state}>
            <span className="flex h-[18px] w-4 shrink-0 items-center justify-center">
              <Mark state={s.state} />
            </span>
            <span className={cn("min-w-0 wrap-break-word", s.state === "pending" ? "text-ink3" : s.state === "active" ? "font-medium text-ink" : "text-ink2")}>
              <span className="sr-only">{SAID[s.state]}: </span>
              {s.text}
              {s.state === "active" && s.since && <Elapsed since={s.since} />}
            </span>
          </li>
        ))}
      </ol>
      {note && (
        <p className="m-0 border-t border-sunken px-4 py-2.5 text-[13px] text-ink3" data-kind="progress-note">
          {note}
        </p>
      )}
    </div>
  );
}

/** How long the step under way has taken, on the clock's tick. */
function Elapsed({ since }: { since: string }) {
  const now = useNow();
  const seconds = now === null ? null : (now - new Date(since).getTime()) / 1000;
  if (seconds === null || !(seconds >= 0)) return null;
  return (
    <span className="ml-1.5 font-normal text-ink3" aria-hidden="true">
      {took(seconds)}
    </span>
  );
}
