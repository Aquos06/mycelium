"use client";

// Modules: what is grown and what is core, each a card with its wiring and a figure.

import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useBus } from "@/lib/bus";
import { CORE, type CoreService } from "@/lib/core";
import { sparkline, usd } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useCoreStatus, useModules, useUsage } from "@/lib/queries";
import { Button } from "@/components/ui/Button";
import { Empty, ErrorLine, Mono, Seg } from "@/components/ui/Primitives";
import { Page, PageInner, Right, Title, Topbar } from "@/components/ui/Topbar";
import { CoreCard } from "./CoreCard";
import { ModuleCard } from "./ModuleCard";
import { coreKind } from "./coreKind";

type Filter = "all" | "grown" | "core";

export function Modules() {
  const [filter, setFilter] = useState<Filter>("all");
  const { events } = useBus();
  const mods = useModules();
  const { data: usage } = useUsage();
  const core = useCoreStatus();
  const now = useNow() ?? 0;

  const grown = mods.modules.map((m) => {
    const mine = events.filter((e) => e.subject.startsWith(`mod.${m.name}.`));
    return { m, count: mine.length, spark: sparkline(mine.map((e) => e.received), 7, now) };
  });

  const coreMetric = (c: CoreService): [string, string] => {
    switch (c.name) {
      case "supervisor":
        return [String(mods.modules.length), mods.modules.length === 1 ? "module" : "modules"];
      case "gateway":
        return usage ? [usd(usage.usd), `of ${usd(usage.budget_usd_month)} this month`] : ["—", "spend this month"];
      case "main": {
        const n = events.filter((e) => e.subject === "trace.plan").length;
        return [String(n), n === 1 ? "reply planned" : "replies planned"];
      }
      case "web":
        return [String(events.length), "events on this page"];
      case "telegram": {
        const n = events.filter((e) => e.subject === "sense.chat" && e.data.channel === "telegram").length;
        return [String(n), "messages seen"];
      }
      default:
        return ["—", ""];
    }
  };

  return (
    <>
      <Topbar>
        <Title>Modules</Title>
        <Seg
          value={filter}
          onChange={setFilter}
          options={[
            { id: "all", label: "All" },
            { id: "grown", label: "Grown" },
            { id: "core", label: "Core" },
          ]}
        />
        <Right>
          {mods.error && <ErrorLine>{mods.error}</ErrorLine>}
          <Button size="sm" onClick={mods.refresh} title="Ask the supervisor again">
            <RefreshCw className="size-[13px]" /> Refresh
          </Button>
        </Right>
      </Topbar>
      <Page>
        <PageInner className="max-w-[1120px]">
          {(filter === "all" || filter === "grown") && (
            <section className="flex flex-col gap-3" aria-label="Grown">
              <SectionHead title="Grown" sub={mods.loading ? "asking the supervisor…" : "built for you, run by the supervisor"} />
              {!mods.loading && grown.length === 0 && (
                <Empty>
                  Nothing deployed. <Mono>make deploy-hello</Mono> starts the example module; a spec in <Mono>specs/</Mono> grows a new one with the
                  builder.
                </Empty>
              )}
              <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">
                {grown.map(({ m, count, spark }) => (
                  <ModuleCard key={m.name} m={m} count={count} spark={spark} health={mods.health[m.name]} />
                ))}
              </div>
            </section>
          )}
          {(filter === "all" || filter === "core") && (
            <section className="flex flex-col gap-3" aria-label="Core">
              <SectionHead title="Core" sub="the system itself" />
              <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">
                {CORE.map((c) => {
                  const [metric, label] = coreMetric(c);
                  return <CoreCard key={c.name} c={c} status={coreKind(core[c.name], c.optional)} metric={metric} metricLabel={label} />;
                })}
              </div>
            </section>
          )}
        </PageInner>
      </Page>
    </>
  );
}

function SectionHead({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <h2 className="m-0 text-[15px] font-semibold">{title}</h2>
      <span className="text-[12.5px] text-ink3">{sub}</span>
    </div>
  );
}
