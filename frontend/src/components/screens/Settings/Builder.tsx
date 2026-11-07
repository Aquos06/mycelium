"use client";

// Who writes a module when a build names none: ours, through the gateway's coder slot, or a coding agent the
// supervisor runs. The one setting this page writes: the builder keeps the choice across restarts.

import { builderError, useChooseCoder, useCoders } from "@/lib/queries";
import type { CoderInfo } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { Card, Empty, ErrorLine, Mono, Note, Spinner, Tag } from "@/components/ui/Primitives";
import { Heading } from "./index";

export function Builder() {
  const coders = useCoders();
  const choose = useChooseCoder();
  const error = builderError(coders.error);
  const list = coders.data;
  return (
    <>
      <Heading
        title="Builder"
        lead="Who writes a module when a build names none. Ours writes it file by file through the gateway's coder slot; a coding agent works in a container of its own. Every coder's module is judged the same way: the checks, then its tests in the sealed box."
      />
      {error && <ErrorLine>{error}</ErrorLine>}
      {choose.error && <ErrorLine>{builderError(choose.error)}</ErrorLine>}
      {list && (
        <section className="flex flex-col gap-2.5" aria-label="Coders">
          <Card className="overflow-hidden">
            {list.coders.map((c) => (
              <CoderRow
                key={c.name}
                c={c}
                chosen={c.name === list.default}
                busy={choose.isPending && choose.variables === c.name}
                disabled={choose.isPending}
                onUse={() => choose.mutate(c.name)}
              />
            ))}
            <Note>
              The default starts as <Mono>BUILDER_CODER</Mono> ({list.seed}); a choice here is kept by the builder across restarts. A build can
              still name another (<Mono>mctl build … --coder opencode</Mono>), and builds already waiting keep theirs. Ready means it is set
              up; whether its model answers shows when a build starts.
            </Note>
          </Card>
        </section>
      )}
      {coders.isPending && <Empty>Asking the builder…</Empty>}
    </>
  );
}

function CoderRow({ c, chosen, busy, disabled, onUse }: { c: CoderInfo; chosen: boolean; busy: boolean; disabled: boolean; onUse: () => void }) {
  return (
    <div className={cn("grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-3 border-b border-sunken px-4 py-3", chosen && "bg-paper")} data-coder={c.name}>
      <span className={cn("flex size-4 items-center justify-center rounded-full border-[1.5px] border-ink4", chosen && "border-[5px] border-ink")} aria-hidden="true" />
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <Mono className="text-[13.5px] font-medium">{c.name}</Mono>
          {chosen && <Tag variant="ink">default</Tag>}
        </div>
        {c.description && <span className="text-[12.5px] text-pretty text-ink2">{c.description}</span>}
        {!c.ready && c.reason && <span className="text-[12px] text-amber">{c.reason}</span>}
      </div>
      <div className="flex flex-col items-end gap-1.5 text-[12px]">
        <span className={cn("inline-flex items-center gap-[5px]", c.ready ? "text-moss" : "text-amber")}>
          <span className="size-1.5 rounded-full bg-current" />
          {c.ready ? "Ready" : "Not ready"}
        </span>
        {!chosen && (
          <Button size="sm" disabled={disabled} onClick={onUse} aria-label={`Use ${c.name}`}>
            {busy && <Spinner ink />} Use
          </Button>
        )}
      </div>
    </div>
  );
}
