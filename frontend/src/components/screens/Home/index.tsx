"use client";

// Home: a greeting and the composer, what needs you, today on the bus, what is alive, which senses are on.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useBus } from "@/lib/bus";
import { threads } from "@/lib/chat";
import { dayPart, plural, sparkline } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { ROUTES } from "@/lib/nav";
import { useFeedback, useMissingKeys, useModules, useSendChat } from "@/lib/queries";
import type { BusEvent } from "@/lib/schemas";
import { statusOf } from "@/lib/status";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { Composer } from "@/components/ui/Composer";
import { Logo } from "@/components/ui/Logo";
import { Empty, Label, Spark } from "@/components/ui/Primitives";
import { Page, PageInner } from "@/components/ui/Topbar";
import { AttentionCard } from "./AttentionCard";
import { Timeline } from "./Timeline";

const PROMPTS = ["What did I do yesterday?", "What is running right now?", "What do you remember about me?"];
const SENSES: { k: string; name: string; subject: string; off: string }[] = [
  { k: "chat", name: "Chat", subject: "sense.chat", off: "no messages yet" },
  { k: "voice", name: "Voice", subject: "sense.voice", off: "not set up" },
  { k: "screen", name: "Screen", subject: "sense.screen", off: "not set up" },
  { k: "camera", name: "Camera", subject: "sense.cam", off: "not set up" },
  { k: "iot", name: "Home", subject: "sense.iot", off: "not set up" },
];

export function Home() {
  const router = useRouter();
  const { events, name } = useBus();
  const { modules } = useModules();
  const missingKeys = useMissingKeys();
  const send = useSendChat();
  const feedback = useFeedback();
  const now = useNow();
  const [raw, setRaw] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());

  const recent = useMemo(() => events.slice().reverse(), [events]);
  const lastHour = now ? recent.filter((e) => now - new Date(e.received).getTime() < 3600_000).length : 0;
  const alive = modules.filter((m) => statusOf(m) === "running");

  const answered = useMemo(
    () => new Set(events.filter((e) => e.subject === "sense.feedback" && e.data.answer).map((e) => String(e.data.ref))),
    [events],
  );
  const asks = recent.filter((e) => e.subject === "out.ask" && !answered.has(String(e.data.ref ?? e.data.id))).slice(0, 4);
  const notes = recent.filter((e) => e.subject === "out.notify" && !dismissed.has(String(e.data.id ?? e.seq))).slice(0, 3);

  const summary = now
    ? `A ${lastHour > 20 ? "busy" : "quiet"} ${dayPart(new Date(now))}: ${[
        lastHour ? `${plural(lastHour, "thing")} happened on the bus in the last hour` : "nothing on the bus in the last hour",
        alive.length ? `${plural(alive.length, "module")} alive` : "no modules alive",
        asks.length ? `${plural(asks.length, "question")} waiting for you` : "nothing waiting for you",
      ].join(", ")}.`
    : "";

  const tiles = alive.slice(0, 4).map((m) => {
    const mine = events.filter((e) => e.subject.startsWith(`mod.${m.name}.`));
    return { m, count: mine.length, spark: sparkline(mine.map((e) => e.received), 7, now ?? 0) };
  });

  const senses = SENSES.map((s) => {
    const seen = events.filter((e) => e.subject === s.subject);
    const sources = [...new Set(seen.map((e) => String(e.data.channel ?? e.data.source ?? "")).filter(Boolean))];
    return { ...s, on: seen.length > 0, sub: seen.length ? sources.join(" · ") || "on" : s.off };
  });

  const say = async (text: string) => {
    await send.mutateAsync({ text, thread: "web" });
    threads.touch("web", text);
    router.push(ROUTES.chat("web"));
  };

  const answer = (e: BusEvent, choice: string) =>
    feedback.mutate({ ref: String(e.data.ref ?? e.data.id), thread: String(e.data.thread ?? "web"), answer: choice });

  return (
    <Page paper>
      <PageInner className="max-w-[960px] gap-8 px-4 pt-8 pb-12 md:gap-11 md:px-10 md:pt-14 md:pb-20">
        <section className="mx-auto flex w-full max-w-[720px] flex-col items-center gap-[18px] text-center">
          <Link href={ROUTES.voice} className="flex size-14 drop-shadow-[0_6px_18px_rgba(46,125,79,0.28)]" title="Talk (⌘J)" aria-label="Talk">
            <Logo draw />
          </Link>
          <div className="flex flex-col items-center gap-2">
            <h1 className="text-[28px] leading-[1.1] font-semibold tracking-[-0.03em] md:text-[34px]">
              {now ? `Good ${dayPart(new Date(now))}, ${name || "there"}` : `Hello, ${name || "there"}`}
            </h1>
            <span className="max-w-[560px] text-[15.5px] leading-normal text-pretty text-ink2">{summary}</span>
          </div>
          <Composer placeholder="Ask, log, or tell me something…" onSend={say} talkLabel className="mt-1.5 w-full pt-3.5" />
          <div className="flex flex-wrap justify-center gap-1.5">
            {PROMPTS.map((p) => (
              <button
                key={p}
                type="button"
                className="flex h-[30px] items-center rounded-[15px] bg-sunken px-3 text-[13px] text-ink2 hover:bg-hover hover:text-ink"
                onClick={() => void say(p)}
              >
                {p}
              </button>
            ))}
          </div>
        </section>

        {(asks.length > 0 || notes.length > 0 || missingKeys.length > 0) && (
          <section className="flex flex-col gap-3" aria-label="Needs you">
            <Label lg>Needs you</Label>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3">
              {asks.map((e) => (
                <AttentionCard key={e.seq} subject="out.ask" glyph="?" title={String(e.data.text ?? "")} body={`Asked on ${String(e.data.channel ?? "the bus")}`} at={e.received}>
                  <div className="flex flex-wrap items-center gap-2">
                    {((e.data.choices as string[] | undefined) ?? []).map((c) => (
                      <Button key={c} variant="primary" onClick={() => answer(e, c)} disabled={feedback.isPending}>
                        {c}
                      </Button>
                    ))}
                  </div>
                </AttentionCard>
              ))}
              {notes.map((e) => (
                <AttentionCard key={e.seq} subject="out.notify" glyph="!" title={String(e.data.text ?? "")} body={`From ${String(e.data.source ?? "the bus")}`} at={e.received}>
                  <div>
                    <Button variant="primary" onClick={() => setDismissed((d) => new Set(d).add(String(e.data.id ?? e.seq)))}>
                      Got it
                    </Button>
                  </div>
                </AttentionCard>
              ))}
              {missingKeys.map((env) => (
                <AttentionCard key={env} subject="sys.settings" glyph="k" title={`${env} is not set`} body="The active provider of a slot needs this key; its calls fail until the key is in .env.">
                  <div>
                    <Button variant="primary" onClick={() => router.push(ROUTES.settings("keys"))}>
                      See keys
                    </Button>
                  </div>
                </AttentionCard>
              ))}
            </div>
          </section>
        )}

        <div className="flex flex-wrap items-start gap-12">
          <section className="flex min-w-0 flex-[1_1_440px] flex-col gap-3.5" aria-label="Today">
            <div className="flex items-center gap-2">
              <Label lg>Today</Label>
              <span className="flex items-center gap-[5px] text-[12px] text-moss">
                <span className="size-1.5 animate-pulse-soft rounded-full bg-current" />
                live
              </span>
              <button
                type="button"
                aria-pressed={raw}
                className={cn("ml-auto flex h-6 items-center rounded-xl bg-sunken px-[9px] font-mono text-[11.5px] text-ink2", raw && "bg-ink text-white")}
                onClick={() => setRaw((r) => !r)}
              >
                raw bus
              </button>
            </div>
            {recent.length === 0 || now === null ? (
              <Empty>Nothing on the bus since the gateway started. Say something, or deploy a module.</Empty>
            ) : (
              <Timeline events={recent.slice(0, 60)} raw={raw} now={now} />
            )}
          </section>

          <aside className="flex min-w-[240px] flex-[0_1_280px] flex-col gap-8">
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <Label lg>Alive</Label>
                <Link href={ROUTES.modules} className="ml-auto text-[12.5px] text-ink2 no-underline hover:text-ink">
                  All →
                </Link>
              </div>
              {tiles.length === 0 && <Empty>No module is running. Deploy one from Modules.</Empty>}
              {tiles.map(({ m, count, spark }) => (
                <Link
                  key={m.name}
                  href={ROUTES.module(m.name)}
                  className="-mx-2.5 flex items-center gap-2.5 rounded-lg px-2.5 py-[9px] text-left text-ink no-underline hover:bg-sunken"
                >
                  <span className="size-[7px] shrink-0 rounded-full bg-moss" />
                  <span className="flex min-w-0 flex-1 flex-col leading-[1.3]">
                    <span className="font-mono text-[13px] font-medium">{m.name}</span>
                    <span className="text-[12px] text-ink3">
                      {count} {count === 1 ? "event" : "events"} seen
                    </span>
                  </span>
                  <Spark values={spark} small />
                </Link>
              ))}
            </div>
            <div className="flex flex-col gap-2.5">
              <Label lg>Senses</Label>
              <div className="flex flex-wrap gap-1.5">
                {senses.map((s) => (
                  <span
                    key={s.k}
                    title={s.sub}
                    className={cn(
                      "inline-flex h-[30px] items-center gap-[7px] rounded-[15px] border border-line-strong bg-surface pr-3 pl-2.5 text-[13px] text-ink",
                      !s.on && "border-dashed bg-transparent text-ink3",
                    )}
                  >
                    <span className={cn("size-1.5 rounded-full", s.on ? "bg-moss" : "bg-line-strong")} />
                    {s.name}
                  </span>
                ))}
              </div>
              <span className="text-[12px] text-ink3">
                {senses.filter((s) => s.on).length === 0
                  ? "A sense lights up once something arrives on its subject."
                  : senses
                      .filter((s) => s.on)
                      .map((s) => `${s.name}: ${s.sub}`)
                      .join(" · ")}
              </span>
            </div>
          </aside>
        </div>
      </PageInner>
    </Page>
  );
}
