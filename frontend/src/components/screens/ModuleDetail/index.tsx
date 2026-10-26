"use client";

// One module: what it is, how it is wired, ask it directly, what it did lately, its properties.
// A core service gets the same page from its description in lib/core.ts.

import { useMemo } from "react";
import { useBus } from "@/lib/bus";
import { CORE } from "@/lib/core";
import { payload } from "@/lib/domains";
import { hhmm } from "@/lib/format";
import { ROUTES } from "@/lib/nav";
import { useCoreStatus, useModules } from "@/lib/queries";
import type { BusEvent } from "@/lib/schemas";
import { statusOf } from "@/lib/status";
import { Empty, ErrorLine, Label, Mark, Mono, Pill } from "@/components/ui/Primitives";
import { Crumb, Page, PageInner, Right, Sep, Title, Topbar } from "@/components/ui/Topbar";
import { coreKind } from "@/components/screens/Modules/coreKind";
import { AskIt } from "./AskIt";
import { Controls } from "./Controls";
import { Wiring } from "./Wiring";
import { coreProps, moduleProps } from "./props";

export function ModuleDetail({ name }: { name: string }) {
  const { events } = useBus();
  const mods = useModules();
  const coreUp = useCoreStatus();
  const m = mods.modules.find((x) => x.name === name);
  const core = CORE.find((c) => c.name === name);

  const mine = useMemo(() => {
    const own = (e: BusEvent) =>
      e.subject.startsWith(`mod.${name}.`) ||
      (e.subject.startsWith("sys.") && e.data.name === name) ||
      (core ? core.emits.some((s) => e.subject === s) || e.data.source === name : false);
    return events.filter(own).slice().reverse().slice(0, 40);
  }, [events, name, core]);

  if (!m && !core) {
    return (
      <>
        <Crumbs name={name} />
        <Page>
          <PageInner>
            <Empty>{mods.loading ? "Asking the supervisor…" : `The supervisor knows no module named ${name}.`}</Empty>
          </PageInner>
        </Page>
      </>
    );
  }

  const status = m ? { kind: statusOf(m), label: undefined as string | undefined } : coreKind(coreUp[name], core?.optional);
  const health = m ? mods.health[m.name] : undefined;
  const unhealthy = m && status.kind === "running" && health && !health.ok;
  const purpose = m ? m.manifest.purpose : core!.purpose;
  const need = m ? m.manifest.need : core!.need;

  return (
    <>
      <Crumbs name={name}>{m && <Controls m={m} />}</Crumbs>
      <Page>
        <PageInner className="max-w-[1080px] flex-row flex-wrap items-start gap-10 md:pt-8">
          <div className="flex min-w-0 flex-[1_1_520px] flex-col gap-8">
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="m-0 font-mono text-[26px] font-medium tracking-[-0.02em]">{name}</h1>
                {unhealthy ? <Pill kind="failed" label="Unhealthy" /> : <Pill kind={status.kind} label={status.label} />}
                {m && <span className="text-[13px] text-ink3">v{m.version}</span>}
              </div>
              <span className="max-w-[600px] text-[15px] text-pretty text-ink1">{purpose}</span>
              {need && <span className="max-w-[600px] text-[13px] text-pretty text-ink3">Why it exists: {need}</span>}
              {unhealthy && <ErrorLine>Health check: {health?.error ?? health?.status ?? "not ok"}</ErrorLine>}
            </div>

            <div className="flex flex-col gap-3">
              <Label>Wiring</Label>
              <Wiring
                name={name}
                kind={status.kind}
                listens={m ? m.manifest.subscribes : core!.listens}
                emits={m ? m.manifest.emits.map((e) => `mod.${name}.${e}`) : core!.emits}
                answers={m ? m.manifest.requests.map((a) => `${name}.${a}`) : core!.answers}
              />
            </div>

            {m && <AskIt key={m.name} m={m} />}

            <div className="flex flex-col gap-1.5">
              <Label className="pb-1.5">Recent events</Label>
              {mine.length === 0 && <Empty>Nothing from {name} since the gateway started.</Empty>}
              <ol className="m-0 list-none p-0">
                {mine.map((e) => (
                  <li key={`${e.received}|${e.seq}`} className="grid grid-cols-[8px_72px_minmax(0,1fr)] items-center gap-3 border-b border-sidebar py-[7px] text-[13px]">
                    <Mark subject={e.subject} square size={7} />
                    <span className="font-mono text-[11.5px] text-ink3">{hhmm(e.received)}</span>
                    <span className="flex min-w-0 items-baseline gap-2.5">
                      <Mono className="text-[12px] whitespace-nowrap text-ink2">{e.subject}</Mono>
                      <span className="truncate text-ink1" title={payload(e.data, 400)}>
                        {payload(e.data)}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          </div>

          <aside className="flex min-w-[240px] flex-[0_1_280px] flex-col gap-0.5 md:border-l md:border-sunken md:pl-6" aria-label="Properties">
            <Label className="pb-2">Properties</Label>
            {(m ? moduleProps(m, health) : coreProps(core!)).map(([k, v, mono]) => (
              <div key={k} className="grid grid-cols-[96px_minmax(0,1fr)] gap-2.5 py-[7px] text-[13px]">
                <span className="text-ink3">{k}</span>
                <span className={mono ? "font-mono text-[12.5px] wrap-break-word" : "text-[12.5px] wrap-break-word"}>{v}</span>
              </div>
            ))}
          </aside>
        </PageInner>
      </Page>
    </>
  );
}

function Crumbs({ name, children }: { name: string; children?: React.ReactNode }) {
  return (
    <Topbar>
      <Crumb href={ROUTES.modules}>Modules</Crumb>
      <Sep />
      <Title mono>{name}</Title>
      <Right>{children}</Right>
    </Topbar>
  );
}
