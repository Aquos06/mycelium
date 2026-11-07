"use client";

// What the module has, as its views show it: each one built by the gateway from what the module answers now (a
// table of entries, a chart, the week's numbers), refreshed every minute and whenever the module says something on
// the bus. A view that could not be shown says why; the others still show. A module that declares no views is
// shown from the replies of its requests that need nothing and only read.

import { RefreshCw } from "lucide-react";
import { Blocks } from "@/components/ui/blocks";
import { Empty, ErrorLine, Label } from "@/components/ui/Primitives";
import { useModuleViews, viewsError } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function Data({ name }: { name: string }) {
  const q = useModuleViews(name);
  const page = q.data;
  const shown = page?.views.filter((v) => v.block) ?? [];
  const failed = page?.views.filter((v) => !v.block) ?? [];

  return (
    <section className="flex flex-col gap-3" aria-label="Data">
      <div className="flex items-center justify-between gap-3">
        <Label>Data</Label>
        <button
          type="button"
          onClick={() => void q.refetch()}
          disabled={q.isFetching}
          className="inline-flex h-7 items-center gap-1.5 rounded-row px-2 text-[12.5px] text-ink3 hover:bg-hover hover:text-ink disabled:opacity-60"
        >
          <RefreshCw className={cn("size-3.5", q.isFetching && "animate-spin-fast")} aria-hidden="true" />
          Refresh
        </button>
      </div>
      {q.isPending ? (
        <Empty>Asking {name}…</Empty>
      ) : q.isError ? (
        <ErrorLine>{viewsError(q.error)}</ErrorLine>
      ) : !page?.running ? (
        <Empty>{name} is not running, so there is no one to ask for its data.</Empty>
      ) : page.views.length === 0 ? (
        <Empty>{name} has no view of its data, and no request a page can ask on its own.</Empty>
      ) : (
        <>
          <Blocks blocks={shown.map((v) => v.block!)} />
          {failed.map((v) => (
            <p key={v.id} className="m-0 text-[12.5px] text-ink3" data-kind="view-error">
              <span className="text-ink2">{v.title || v.id}</span>: {v.error}
            </p>
          ))}
          {!page.declared && (
            <p className="m-0 text-[12.5px] text-ink3">
              Made from its replies: {name} declares no views. A change to it can add them (`views` in its manifest).
            </p>
          )}
        </>
      )}
    </section>
  );
}
