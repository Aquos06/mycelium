"use client";

// The slots and their providers, as the gateway loaded them; the month's spend against the budget.

import { usd } from "@/lib/format";
import { gatewayError, useGatewayConfig, useUsage } from "@/lib/queries";
import type { ProviderInfo } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import { Card, Empty, ErrorLine, Mono, Note, Tag } from "@/components/ui/Primitives";
import { Heading } from "./index";
import { SLOT_WORDS } from "./env";

export function Models() {
  const config = useGatewayConfig();
  const { data: usage } = useUsage();
  const error = gatewayError(config.error);
  return (
    <>
      <Heading
        title="Models"
        lead="Each slot is one job the system needs a model for. The active provider answers; a shadow gets every request too and only logs. Keys stay in the stack's environment, this page only sees whether they are set."
      />
      {error && <ErrorLine>{error}</ErrorLine>}
      {usage && (
        <Card className="flex flex-col gap-3 px-[18px] py-4" aria-label="Monthly budget">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-[14px] font-semibold">Monthly budget</span>
            <Mono className="text-[11.5px] text-ink3">budget_usd_month</Mono>
            <span className="ml-auto text-[20px] font-semibold tracking-[-0.02em]">
              {usd(usage.usd)}{" "}
              <small className="text-[13px] font-normal text-ink3">of {usage.budget_usd_month === null ? "no limit" : usd(usage.budget_usd_month)}</small>
            </span>
          </div>
          <div className="flex h-1.5 overflow-hidden rounded-[3px] bg-sunken">
            <div
              className="bg-brain transition-[width] duration-500"
              style={{ width: usage.budget_usd_month ? `${Math.min(100, (usage.usd / usage.budget_usd_month) * 100).toFixed(1)}%` : "0%" }}
            />
          </div>
          <div className="flex flex-wrap gap-4 text-[12.5px] text-ink2">
            <span>
              <span className="mr-1.5 inline-block size-2 rounded-[2px] bg-brain align-middle" />
              {usage.calls} {usage.calls === 1 ? "call" : "calls"} in {usage.month}
            </span>
            <span>
              {(usage.input_tokens / 1000).toFixed(1)}k tokens in · {(usage.output_tokens / 1000).toFixed(1)}k out
            </span>
            <span className="ml-auto text-ink3">Resets on the 1st</span>
          </div>
        </Card>
      )}
      {config.data &&
        Object.entries(config.data.slots).map(([name, slot]) => {
          const [title, desc] = SLOT_WORDS[name] ?? [name[0].toUpperCase() + name.slice(1), `The ${name} slot.`];
          return (
            <section key={name} className="flex flex-col gap-2.5" aria-label={title}>
              <div className="flex flex-wrap items-baseline gap-2.5">
                <h2 className="m-0 text-[15px] font-semibold">{title}</h2>
                <Mono className="text-[11.5px] text-ink3">{name.toUpperCase()}_PROVIDER</Mono>
                {slot.task !== "complete" && <Tag>{slot.task}</Tag>}
              </div>
              <span className="-mt-1.5 text-[13px] text-pretty text-ink2">{desc}</span>
              <Card className="overflow-hidden">
                {Object.entries(slot.providers).map(([pname, p]) => (
                  <ProviderRow key={pname} name={pname} p={p} active={slot.active === pname} shadow={slot.shadow === pname} />
                ))}
                <Note>
                  {slot.shadow
                    ? `${slot.shadow} shadows ${slot.active}: it gets every request and only logs, for comparing before you switch.`
                    : "No shadow. To try another provider side by side, set `shadow:` on this slot in providers.yaml."}
                </Note>
              </Card>
            </section>
          );
        })}
      {config.isPending && <Empty>Asking the gateway…</Empty>}
      <Note className="rounded-card border border-line">
        Read-only for now. The seed is <Mono>services/gateway/providers.yaml</Mono>; which provider is active comes from{" "}
        <Mono>&lt;SLOT&gt;_PROVIDER</Mono> in <Mono>.env</Mono>. Change either and restart the gateway.
      </Note>
    </>
  );
}

function ProviderRow({ name, p, active, shadow }: { name: string; p: ProviderInfo; active: boolean; shadow: boolean }) {
  const key =
    p.key_state === "not-needed"
      ? { cls: "text-ink3", text: "Local · no key" }
      : p.key_state === "ok"
        ? { cls: "text-moss", text: `${p.key_env} set` }
        : { cls: "text-amber", text: `${p.key_env} missing` };
  const price =
    p.price_in_per_m || p.price_out_per_m ? `$${p.price_in_per_m} in · $${p.price_out_per_m} out / M` : p.key_state === "not-needed" ? "free" : "—";
  return (
    <div className={cn("grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-3 border-b border-sunken px-4 py-3", active && "bg-paper")} data-provider={name}>
      <span className={cn("flex size-4 items-center justify-center rounded-full border-[1.5px] border-ink4", active && "border-[5px] border-ink")} aria-hidden="true" />
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <Mono className="text-[13.5px] font-medium">{p.model}</Mono>
          <Tag>{name === p.kind ? p.kind : `${name} · ${p.kind}`}</Tag>
          {active && <Tag variant="ink">active</Tag>}
          {shadow && <Tag variant="dashed">shadow</Tag>}
        </div>
        <Mono className="truncate text-[11.5px] text-ink3">
          {p.endpoint ?? "Anthropic SDK"} · max_tokens {p.max_tokens}
        </Mono>
      </div>
      <div className="flex flex-col items-end gap-[3px] text-[12px] text-ink3">
        <span className={cn("inline-flex items-center gap-[5px]", key.cls)}>
          <span className="size-1.5 rounded-full bg-current" />
          {key.text}
        </span>
        <span>{price}</span>
      </div>
    </div>
  );
}
