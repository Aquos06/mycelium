"use client";

// Ask a module directly: pick one of its actions, give JSON arguments, see what it answers.
// Mounted with `key={m.name}` by its page, so another module is a fresh form.

import { useState, type KeyboardEvent } from "react";
import { useAskModule } from "@/lib/queries";
import type { Json, ModuleRow } from "@/lib/schemas";
import { Button } from "@/components/ui/Button";
import { Kbd, Label, Mono, Pre, Spinner } from "@/components/ui/Primitives";

export function AskIt({ m }: { m: ModuleRow }) {
  const actions = [...m.manifest.requests, "health"];
  const [action, setAction] = useState(actions[0]);
  const [args, setArgs] = useState("{}");
  const [parseError, setParseError] = useState<string | null>(null);
  const ask = useAskModule();

  const run = () => {
    let parsed: Json;
    try {
      parsed = args.trim() ? (JSON.parse(args) as Json) : {};
    } catch {
      setParseError("the arguments are not valid JSON");
      return;
    }
    setParseError(null);
    ask.mutate({ name: m.name, action, args: parsed });
  };
  const onKey = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") run();
  };

  const result = parseError ?? (ask.error ? ask.error.message : ask.data ? JSON.stringify(ask.data, null, 2) : null);
  const field = "h-[30px] rounded-btn border border-line-strong bg-surface px-2 font-mono text-[12.5px] outline-none";

  return (
    <div className="flex flex-col gap-3">
      <Label>Ask it directly</Label>
      <div className="overflow-hidden rounded-card border border-line bg-surface">
        <div className="flex flex-wrap items-center gap-2.5 px-3 py-2.5">
          <Mono className="text-[12.5px] text-ink2">rpc.mod.{m.name}.</Mono>
          <select value={action} onChange={(e) => setAction(e.target.value)} className={field} aria-label="Action">
            {actions.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          <input
            value={args}
            onChange={(e) => setArgs(e.target.value)}
            onKeyDown={onKey}
            placeholder="{}"
            aria-label="Arguments as JSON"
            spellCheck={false}
            className={`${field} min-w-0 flex-[1_1_160px]`}
          />
          <Button variant="primary" disabled={ask.isPending} onClick={run}>
            {ask.isPending && <Spinner ink />} Run <Kbd className="text-ink3">⌘↵</Kbd>
          </Button>
        </div>
        {result !== null && (
          <Pre className="border-t border-sunken" data-testid="ask-result">
            {result}
          </Pre>
        )}
      </div>
    </div>
  );
}
