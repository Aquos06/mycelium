"use client";

// Voice: the screen for talking. Nothing listens yet (sense.voice has no bridge), and the screen says so
// instead of pretending; the orb, the state line and the controls are the real layout for when it does.

import { MessageCircle, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ROUTES } from "@/lib/nav";
import { Arches, Logo } from "@/components/ui/Logo";
import { Chip, Mono } from "@/components/ui/Primitives";

export function Voice() {
  const router = useRouter();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") router.push(ROUTES.home);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <div className="absolute inset-0 z-10 flex flex-col bg-night text-on-night" role="dialog" aria-label="Voice">
      <div className="flex h-14 items-center gap-2.5 px-5">
        <div className="flex size-[22px]">
          <Logo draw />
        </div>
        <span className="font-medium">Voice</span>
        <Chip subject="sense.voice" className="bg-voice-chip text-voice-chip-text" />
        <button
          type="button"
          className="ml-auto flex size-8 items-center justify-center rounded-lg text-on-night-faint hover:bg-night-raised hover:text-on-night"
          onClick={() => router.push(ROUTES.home)}
          title="Close (Esc)"
          aria-label="Close"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-[clamp(16px,4vh,40px)] overflow-hidden px-6 py-3">
        <div className="relative flex w-[min(240px,30vh)] shrink-0 flex-col items-center">
          <div className="pointer-events-none absolute -top-1/4 -left-1/4 aspect-square w-[150%] animate-breathe rounded-full bg-[radial-gradient(circle,rgba(110,200,145,0.16)_0%,rgba(110,200,145,0)_62%)]" />
          <Arches className="relative aspect-square w-full" />
        </div>
        <div className="flex max-w-[560px] flex-col items-center gap-2.5 text-center">
          <span className="flex items-center gap-2 text-[13px] text-on-night-faint">
            <span className="size-1.5 rounded-full bg-rpc" />
            Not connected
          </span>
          <span className="min-h-[26px] text-[17px] leading-normal text-on-night-soft" />
          <span className="text-[22px] leading-[1.4] font-medium tracking-[-0.015em] text-pretty">Voice is not on the bus yet.</span>
          <span className="text-[14px] leading-normal text-pretty text-on-night-faint">
            No wake word, no microphone bridge publishes <Mono>sense.voice</Mono> so far. When one does, this is where you talk and where the answer is
            spoken back. Until then, type.
          </span>
        </div>
      </div>
      <div className="flex shrink-0 items-center justify-center gap-5 px-6 pt-3 pb-[clamp(16px,4vh,40px)]">
        <button type="button" className="flex size-16 items-center justify-center rounded-full bg-red text-white" onClick={() => router.push(ROUTES.home)} title="End" aria-label="End">
          <X className="size-[22px]" />
        </button>
        <button
          type="button"
          className="flex size-14 items-center justify-center rounded-full bg-night-raised text-on-night"
          onClick={() => router.push(ROUTES.chat())}
          title="Type instead"
          aria-label="Type instead"
        >
          <MessageCircle className="size-5" />
        </button>
      </div>
    </div>
  );
}
