"use client";

// Which keys the gateway needs, and whether each one is set. Never a value.

import { useGatewayConfig } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { Card, Empty, Mono, Note } from "@/components/ui/Primitives";
import { Heading } from "./index";
import { KIND_NAMES } from "./env";

export function Keys() {
  const { data: config } = useGatewayConfig();
  const rows = new Map<string, { vendors: Set<string>; slots: Set<string>; ok: boolean }>();
  if (config) {
    for (const [slot, s] of Object.entries(config.slots)) {
      for (const p of Object.values(s.providers)) {
        if (!p.key_env || p.key_state === "not-needed") continue;
        const r = rows.get(p.key_env) ?? { vendors: new Set(), slots: new Set(), ok: p.key_state === "ok" };
        r.vendors.add(KIND_NAMES[p.kind] ?? p.kind);
        r.slots.add(slot);
        rows.set(p.key_env, r);
      }
    }
  }
  return (
    <>
      <Heading
        title="API keys"
        lead={
          <>
            Keys live in the stack&apos;s environment (<Mono>.env</Mono>), never in providers.yaml and never on the bus. The gateway reports only
            whether each one it needs is set.
          </>
        }
      />
      <Card>
        {rows.size === 0 && <Empty className="p-4">{config ? "No provider in providers.yaml needs a key." : "Asking the gateway…"}</Empty>}
        {[...rows.entries()].map(([env, r]) => (
          <div key={env} className="flex flex-wrap items-center gap-3.5 border-b border-sunken px-[18px] py-3 last:border-b-0" data-key={env}>
            <span className={cn("size-[7px] shrink-0 rounded-full", r.ok ? "bg-moss" : "bg-line-strong")} />
            <div className="flex min-w-0 flex-[1_1_200px] flex-col leading-[1.35]">
              <span className="text-[13.5px] font-medium">{[...r.vendors].join(", ")}</span>
              <span className="text-[12px] text-ink3">
                <Mono>{env}</Mono> · used by {[...r.slots].join(", ")}
              </span>
            </div>
            <Mono className={cn("text-[12.5px]", !r.ok && "text-ink3")}>{r.ok ? "set" : "not set"}</Mono>
          </div>
        ))}
      </Card>
      <Note className="rounded-card border border-line">
        To add or change a key, put it in <Mono>.env</Mono> and restart the gateway (<Mono>docker compose up -d gateway</Mono>). A settings page
        that writes keys back is deliberately not here yet.
      </Note>
    </>
  );
}
