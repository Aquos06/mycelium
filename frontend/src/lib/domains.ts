// Colour means a place on the bus (design system, 01 Color): six domain hues map one-to-one to subject
// prefixes and are the only accents. The values are the same ones app/globals.css declares as tokens;
// they live here too because a mark's colour is data (the subject decides it), not a class name.
//
// Also the reading of an event for the timeline: one plain sentence about what happened, the way you
// would say it (replied this, remembered that, asked the planner model). The machine's side (subject,
// payload, numbers) is `meta`, shown only when the timeline is in raw mode.

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

const num = (v: unknown): number => (typeof v === "number" ? v : 0);
const money = (usd: unknown) => (typeof usd === "number" && usd > 0 ? `$${usd.toFixed(4)}` : "free");
const quote = (t: unknown) => `“${str(t, 110)}”`;

/** The compact payload: the envelope fields dropped, the rest as one short JSON line. */
export function payload(data: Json, max = 120): string {
  const rest: Json = {};
  for (const [k, v] of Object.entries(data)) if (!["id", "ts", "source", "cause", "hops"].includes(k)) rest[k] = v;
  return str(rest, max);
}

/** What a tool call was, in words, for the plan's sentence. */
const TOOL_WORDS: Record<string, string> = {
  "memory.remember": "remembered it",
  "memory.recall": "looked things up",
  "memory.lookup": "looked something up",
  "sys.list": "checked the modules",
  "sys.health": "checked the modules' health",
  ask: "asked you",
};
const toolWords = (name: string) => TOOL_WORDS[name] ?? (name.startsWith("mod.") ? `asked ${name.split(".")[1]}` : `used ${name}`);

/** A few scalar fields of a module event, in words: "count 13 · day 2026-10-26". */
function figures(data: Json, max = 2): string {
  const out: string[] = [];
  for (const [k, v] of Object.entries(data)) {
    if (["id", "ts", "source", "cause", "hops", "channel", "thread"].includes(k)) continue;
    if (typeof v === "number" || typeof v === "boolean" || (typeof v === "string" && v.length <= 24)) out.push(`${k} ${v}`);
    if (out.length === max) break;
  }
  return out.join(" · ");
}

/** True for a sweep that found nothing to do: shown only in raw mode, or the timeline is all of them. */
export function isNoise(e: BusEvent): boolean {
  const d = e.data;
  switch (e.subject) {
    case "trace.embed":
      return num(d.embedded) === 0;
    case "trace.decide":
      return num(d.scored) === 0;
    case "trace.consolidate":
      return d.ok !== false && !num(d.facts);
    case "trace.llm":
      return typeof d.op === "string" && d.op !== "complete"; // the embed and decide sweeps have their own rows
    default:
      return false;
  }
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
  const on = d.channel && d.channel !== "web" ? ` on ${str(d.channel, 20)}` : "";
  switch (true) {
    case sub === "sense.chat":
      return { text: `You said ${quote(d.text)}${on}`, meta: `sense.chat · ${source}` };
    case sub === "sense.feedback":
      return {
        text: d.answer ? `You answered ${quote(d.answer)}` : d.vote === 1 ? "You gave a thumbs up" : "You gave a thumbs down",
        meta: `sense.feedback · ${source}`,
      };
    case sub.startsWith("sense."):
      return { text: `Noticed ${str(d.text ?? d.summary ?? payload(d))}`, meta: `${sub} · ${source}` };
    case sub === "out.say":
      return { text: `Replied ${quote(d.text)}${on}`, meta: `out.say · ${str(d.channel, 20)}` };
    case sub === "out.ask":
      return { text: `Asked you ${quote(d.text)}`, meta: `out.ask · ${(d.choices as string[] | undefined)?.join(" / ") ?? ""}` };
    case sub === "out.notify":
      return { text: `Told you ${quote(d.text)}`, meta: `out.notify · ${source}` };
    case sub === "trace.plan": {
      const tools = (d.tools as { name: string }[] | undefined)?.map((t) => toolWords(t.name)) ?? [];
      const text = d.error ? `Could not answer: ${str(d.error, 90)}` : tools.length ? `Planned a reply and ${tools.join(", ")}` : "Planned a reply";
      return {
        text,
        meta: `trace.plan · ${d.rounds ?? 0} round${d.rounds === 1 ? "" : "s"} · ${money(d.cost_usd)} · ${d.latency_ms ?? 0} ms`,
      };
    }
    case sub === "trace.llm":
      return {
        text: `${d.ok === false ? "Could not reach" : "Asked"} the ${str(d.slot)} model${d.provider ? ` (${str(d.provider, 20)})` : ""}${d.shadow ? ", as a shadow" : ""}`,
        meta: `trace.llm · ${str(d.provider)}${d.model ? ` · ${str(d.model, 40)}` : ""} · ${d.latency_ms ?? 0} ms · ${money(d.cost_usd)}`,
      };
    case sub === "trace.consolidate":
      return {
        text: d.ok === false ? `Could not consolidate ${str(d.day)}` : `Consolidated ${str(d.day)} into ${num(d.facts)} fact${num(d.facts) === 1 ? "" : "s"}`,
        meta: `trace.consolidate · ${d.ok === false ? "failed" : `${str(d.facts ?? "")} facts`}`,
      };
    case sub === "trace.rollup":
      return { text: `${d.ok === false ? "Could not roll up" : "Rolled up"} ${str(d.key ?? d.period)}`, meta: `trace.rollup · ${d.ok === false ? "failed" : "ok"}` };
    case sub === "trace.embed":
      return {
        text: `Embedded ${num(d.embedded)} note${num(d.embedded) === 1 ? "" : "s"}`,
        meta: ["trace.embed", str(d.model, 30), `${d.latency_ms ?? 0} ms`].filter(Boolean).join(" · "),
      };
    case sub === "trace.decide":
      return { text: `Picked ${num(d.picked)} of ${num(d.scored)} notes for the question`, meta: `trace.decide · ${d.latency_ms ?? 0} ms` };
    case sub === "trace.feedback":
      return { text: d.answer ? `Recorded your answer ${quote(d.answer)}` : "Recorded your vote", meta: "trace.feedback" };
    case sub === "brain.observe":
      return { text: str(d.summary ?? payload(d)), meta: `brain.observe · ${source}` };
    case sub.startsWith("sys.module."): {
      const verb = parts[2] === "deployed" ? "Started" : parts[2] === "stopped" ? "Stopped" : parts[2][0].toUpperCase() + parts[2].slice(1);
      return { text: `${verb} ${str(d.name)}`, meta: `${sub}${d.image ? ` · ${str(d.image, 40)}` : ""}` };
    }
    case sub === "sys.reconciled":
      return { text: `Checked ${(d.modules as unknown[] | undefined)?.length ?? 0} modules at start`, meta: sub };
    case sub.startsWith("sys."):
      return { text: str(d.text ?? d.summary ?? payload(d)), meta: sub };
    case sub.startsWith("build."):
      return { text: str(d.text ?? d.summary ?? d.name ?? payload(d)), meta: `${sub} · ${source}` };
    case sub.startsWith("mod."): {
      const what = parts.slice(2).join(" ");
      const f = figures(d);
      return { text: `${parts[1]}: ${what}${f ? ` (${f})` : ""}`, meta: `${sub} · ${payload(d)}` };
    }
    default:
      return { text: payload(d), meta: sub };
  }
}
