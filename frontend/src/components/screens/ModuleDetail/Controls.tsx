"use client";

// Logs, Pause / Start, Rebuild, Delete. Pause and the deploys ask twice (useConfirm); Delete, there for a module the
// builder grew, asks the page to open the dialog that says what happens to it (the page keeps it, not this: these
// controls go with the module's row, which is gone before the deletion is).

import { AlignLeft } from "lucide-react";
import { useState } from "react";
import { useConfirm } from "@/lib/hooks";
import { useModuleAction, useModuleLogs } from "@/lib/queries";
import type { ModuleRow } from "@/lib/schemas";
import { statusOf } from "@/lib/status";
import { Button } from "@/components/ui/Button";
import { ErrorLine, Label, Pre, Spinner } from "@/components/ui/Primitives";

type Act = "stop" | "deploy";

export function Controls({ m, onDelete }: { m: ModuleRow; onDelete?: () => void }) {
  const { armed: arming, confirm } = useConfirm<Act>();
  const [logsOpen, setLogsOpen] = useState(false);
  const action = useModuleAction();
  const logs = useModuleLogs(m.name, logsOpen);
  const running = statusOf(m) === "running";
  const busy: Act | null = action.isPending ? (action.variables?.action ?? null) : null;

  const run = (a: Act) => confirm(a, () => action.mutate({ name: m.name, action: a }));

  return (
    <>
      {action.error && <ErrorLine>{action.error.message}</ErrorLine>}
      <Button size="sm" onClick={() => setLogsOpen((o) => !o)} title="The container's last 200 lines" aria-expanded={logsOpen}>
        <AlignLeft className="size-[13px]" /> <span className="max-sm:sr-only">Logs</span>
      </Button>
      {running ? (
        <Button size="sm" disabled={busy !== null} onClick={() => run("stop")}>
          {busy === "stop" && <Spinner ink />} {arming === "stop" ? "Sure? Pause" : "Pause"}
        </Button>
      ) : (
        <Button size="sm" disabled={busy !== null} onClick={() => run("deploy")}>
          {busy === "deploy" && <Spinner ink />} {arming === "deploy" ? "Sure? Start" : "Start"}
        </Button>
      )}
      <Button size="sm" disabled={busy !== null} onClick={() => run("deploy")} title="Build the image again from modules/ and restart">
        {busy === "deploy" && running && <Spinner ink />} {arming === "deploy" && running ? "Sure? Rebuild" : "Rebuild"}
      </Button>
      {onDelete && (
        <Button size="sm" disabled={busy !== null} onClick={onDelete} aria-haspopup="dialog">
          Delete
        </Button>
      )}
      {logsOpen && (
        <div className="absolute top-12 right-0 left-0 z-10 border-b border-line bg-surface/95 px-6 pb-6" role="region" aria-label="Logs">
          <div className="flex items-center py-2.5">
            <Label>
              docker logs {m.name} · last 200 lines
            </Label>
            <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setLogsOpen(false)}>
              Close
            </Button>
          </div>
          <Pre className="max-h-[60vh] rounded-card border border-line">{logs.isPending ? "…" : logs.error ? logs.error.message : logs.data}</Pre>
        </div>
      )}
    </>
  );
}
