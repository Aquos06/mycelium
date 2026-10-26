"use client";

// Settings: the model slots and their providers as the gateway loaded them, the keys' states, and the
// environment every service reads. Read-only for now: the seed is providers.yaml and .env.

import Link from "next/link";
import { ROUTES, type SettingsTab } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { Card, Mono, Note } from "@/components/ui/Primitives";
import { Title, Topbar } from "@/components/ui/Topbar";
import { ENV, TABS, type EnvRow } from "./env";
import { Keys } from "./Keys";
import { Models } from "./Models";
import { WebTab } from "./WebTab";

export function Settings({ tab }: { tab: SettingsTab }) {
  const env = ENV[tab];
  return (
    <>
      <Topbar>
        <Title>Settings</Title>
        <Mono className="pl-1 text-[11.5px] text-ink3">rpc.llm.config · rpc.llm.usage</Mono>
      </Topbar>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav
          aria-label="Settings"
          className="flex shrink-0 gap-px overflow-x-auto border-b border-sunken px-3 py-2.5 md:w-[200px] md:flex-col md:border-r md:border-b-0 md:py-5"
        >
          {TABS.map((t) => (
            <Link
              key={t.id}
              href={ROUTES.settings(t.id)}
              aria-current={tab === t.id ? "page" : undefined}
              className={cn("flex shrink-0 flex-col rounded-row px-2.5 py-[7px] text-left no-underline hover:bg-sidebar", tab === t.id && "bg-sunken")}
            >
              <span className={cn("text-[13.5px] text-ink2", tab === t.id && "font-medium text-ink")}>{t.label}</span>
              <span className="hidden font-mono text-[11px] text-ink3 md:block">{t.svc}</span>
            </Link>
          ))}
        </nav>
        <div className="min-w-0 flex-1 overflow-y-auto">
          <div className="flex max-w-[820px] flex-col gap-8 px-4 pt-5 pb-16 md:px-8 md:pt-8 md:pb-20">
            {tab === "models" && <Models />}
            {tab === "keys" && <Keys />}
            {env && (
              <>
                <Heading title={env.title} lead={env.desc} />
                <Card>
                  {env.rows.map((r) => (
                    <SettingRow key={r.env} r={r} />
                  ))}
                </Card>
                <Note className="rounded-card border border-line">
                  These are read from the stack&apos;s <Mono>.env</Mono> at start and are not exposed over the bus, so this page shows the variables,
                  not their values.
                </Note>
              </>
            )}
            {tab === "web" && <WebTab />}
          </div>
        </div>
      </div>
    </>
  );
}

export function Heading({ title, lead }: { title: string; lead: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h1 className="m-0 text-[22px] font-semibold tracking-[-0.02em]">{title}</h1>
      <span className="text-[13.5px] text-pretty text-ink2">{lead}</span>
    </div>
  );
}

export function SettingRow({ r }: { r: EnvRow }) {
  return (
    <div className="flex flex-wrap items-center gap-5 border-b border-sunken px-[18px] py-3.5 last:border-b-0">
      <div className="flex min-w-0 flex-[1_1_260px] flex-col gap-0.5">
        <span className="text-[13.5px] font-medium">{r.label}</span>
        <span className="text-[12.5px] text-pretty text-ink2">{r.desc}</span>
        <span className="font-mono text-[11px] text-ink3">{r.env}</span>
      </div>
      <div
        className={cn(
          "flex h-8 min-w-[180px] items-center gap-1.5 rounded-btn border border-line-strong bg-surface px-2.5 font-mono text-[12.5px]",
          !r.value && "border-dashed text-ink3",
        )}
      >
        {r.value ?? "set in .env"}
        {r.unit && <span className="ml-auto font-sans text-[12px] text-ink3">{r.unit}</span>}
      </div>
    </div>
  );
}
