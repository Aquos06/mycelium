// Colour means a place on the bus (design system, 01 Color): six domain hues map one-to-one to subject
// prefixes and are the only accents. The values are the same ones app/globals.css declares as tokens;
// they live here too because a mark's colour is data (the subject decides it), not a class name.
// Also the one-line reading of an event for the timeline.

import type { BusEvent, Domain, Json } from "@/lib/schemas";

export const DOMAIN: Record<Domain, { c: string; soft: string; name: string }> = {
  sense: { c: "#3e63dd", soft: "#ebeffc", name: "Sense" },
  brain: { c: "#7b5cd6", soft: "#f1edfb", name: "Brain" },
  mod: { c: "#2e7d4f", soft: "#e8f2eb", name: "Module" },
  build: { c: "#c2831c", soft: "#faf1e1", name: "Build" },
  sys: { c: "#6b6f76", soft: "#eff0f1", name: "System" },
  out: { c: "#d9573b", soft: "#fbebe6", name: "Out" },
  trace: { c: "#7b5cd6", soft: "#f1edfb", name: "Trace" },
  rpc: { c: "#5c5b56", soft: "#f4f3ef", name: "Request" },
};

export function domainOf(subject: string): Domain {
  const head = subject.split(".")[0];
  return (head in DOMAIN ? head : "sys") as Domain;
}

const str = (v: unknown, max = 140): string => {
  const s = typeof v === "string" ? v : v === undefined || v === null ? "" : JSON.stringify(v);
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
};

const money = (usd: unknown) => (typeof usd === "number" && usd > 0 ? `$${usd.toFixed(4)}` : "free");

/** The compact payload: the envelope fields dropped, the rest as one short JSON line. */
export function payload(data: Json, max = 120): string {
  const rest: Json = {};
  for (const [k, v] of Object.entries(data)) if (!["id", "ts", "source", "cause", "hops"].includes(k)) rest[k] = v;
  return str(rest, max);
}

export interface Reading {
  text: string; // what happened, in words
  meta: string; // the machine's side: subject, source, numbers
}

/** One event as a timeline row reads it. `raw` shows the subject and payload instead of the words. */
export function read(e: BusEvent, raw = false): Reading {
  const d = e.data;
  const source = str(d.source ?? d.channel ?? "", 20);
  if (raw) return { text: e.subject, meta: `${payload(d)}${source ? ` · ${source}` : ""}` };
  const sub = e.subject;
  const parts = sub.split(".");
  const quote = (t: unknown) => `“${str(t, 110)}”`;
  switch (true) {
    case sub === "sense.chat":
      return { text: `You said ${quote(d.text)}`, meta: `sense.chat · ${source}` };
    case sub === "sense.feedback":
      return {
        text: d.answer ? `You answered ${quote(d.answer)}` : d.vote === 1 ? "You gave a thumbs up" : "You gave a thumbs down",
        meta: `sense.feedback · ${source}`,
      };
    case sub.startsWith("sense."):
      return { text: str(d.text ?? d.summary ?? payload(d)), meta: `${sub} · ${source}` };
    case sub === "out.say":
      return { text: `Replied ${quote(d.text)}`, meta: `out.say · ${str(d.channel, 20)}` };
    case sub === "out.ask":
      return { text: `Asked ${quote(d.text)}`, meta: `out.ask · ${(d.choices as string[] | undefined)?.join(" / ") ?? ""}` };
    case sub === "out.notify":
      return { text: `Told you: ${str(d.text)}`, meta: `out.notify · ${source}` };
    case sub === "trace.plan": {
      const tools = (d.tools as { name: string }[] | undefined)?.map((t) => t.name) ?? [];
      const text = d.error ? `Could not answer: ${str(d.error, 90)}` : `Planned a reply${tools.length ? ` with ${tools.join(", ")}` : ""}`;
      return {
        text,
        meta: `trace.plan · ${d.rounds ?? 0} round${d.rounds === 1 ? "" : "s"} · ${money(d.cost_usd)} · ${d.latency_ms ?? 0} ms`,
      };
    }
    case sub === "trace.llm":
      return {
        text: `${d.ok ? "Asked" : "Failed to ask"} the ${str(d.slot)} model${d.shadow ? " (shadow)" : ""}`,
        meta: `trace.llm · ${str(d.provider)}${d.model ? ` · ${str(d.model, 40)}` : ""} · ${d.latency_ms ?? 0} ms · ${money(d.cost_usd)}`,
      };
    case sub === "trace.consolidate":
      return { text: `Consolidated ${str(d.day)}`, meta: `trace.consolidate · ${d.ok === false ? "failed" : `${str(d.facts ?? "")} facts`}` };
    case sub === "trace.rollup":
      return { text: `Rolled up ${str(d.key ?? d.period)}`, meta: `trace.rollup · ${d.ok === false ? "failed" : "ok"}` };
    case sub === "trace.embed":
      return {
        text: `Embedded ${str(d.embedded ?? 0)} notes`,
        meta: ["trace.embed", str(d.model, 30), `${d.latency_ms ?? 0} ms`].filter(Boolean).join(" · "),
      };
    case sub === "trace.decide":
      return { text: `Decided: ${str(d.picked ?? 0)} picked of ${str(d.scored ?? 0)}`, meta: `trace.decide · ${d.latency_ms ?? 0} ms` };
    case sub === "trace.feedback":
      return { text: d.answer ? `Recorded your answer ${quote(d.answer)}` : "Recorded your vote", meta: "trace.feedback" };
    case sub === "brain.observe":
      return { text: str(d.summary ?? payload(d)), meta: `brain.observe · ${source}` };
    case sub.startsWith("sys.module."):
      return { text: `${str(d.name)} ${parts[2]}${d.image ? ` · ${str(d.image, 40)}` : ""}`, meta: sub };
    case sub === "sys.reconciled":
      return { text: `Reconciled ${(d.modules as unknown[] | undefined)?.length ?? 0} modules at start`, meta: sub };
    case sub.startsWith("sys."):
      return { text: payload(d), meta: sub };
    case sub.startsWith("build."):
      return { text: str(d.text ?? d.summary ?? d.name ?? payload(d)), meta: `${sub} · ${source}` };
    case sub.startsWith("mod."):
      return { text: `${parts[1]} · ${parts.slice(2).join(".")}`, meta: payload(d) };
    default:
      return { text: payload(d), meta: sub };
  }
}
