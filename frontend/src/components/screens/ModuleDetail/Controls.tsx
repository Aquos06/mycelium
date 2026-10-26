"use client";

// Logs, Pause / Start, Rebuild. Pause and the deploys ask twice: the second click within four seconds.

import { AlignLeft } from "lucide-react";
import { useState } from "react";
import { useModuleAction, useModuleLogs } from "@/lib/queries";
import type { ModuleRow } from "@/lib/schemas";
import { statusOf } from "@/lib/status";
import { Button } from "@/components/ui/Button";
import { ErrorLine, Label, Pre, Spinner } from "@/components/ui/Primitives";

export function Controls({ m }: { m: ModuleRow }) {
  const [arming, setArming] = useState<"stop" | "deploy" | null>(null);
  const [logsOpen, setLogsOpen] = useState(false);
  const action = useModuleAction();
  const logs = useModuleLogs(m.name, logsOpen);
  const running = statusOf(m) === "running";
  const busy = action.isPending ? action.variables?.action : null;

  const run = (a: "stop" | "deploy") => {
    if (arming !== a) {
      setArming(a);
      window.setTimeout(() => setArming((x) => (x === a ? null : x)), 4000);
      return;
    }
    setArming(null);
    action.mutate({ name: m.name, action: a });
  };

  return (
    <>
      {action.error && <ErrorLine>{action.error.message}</ErrorLine>}
      <Button size="sm" onClick={() => setLogsOpen((o) => !o)} title="The container's last 200 lines" aria-expanded={logsOpen}>
        <AlignLeft className="size-[13px]" /> Logs
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
