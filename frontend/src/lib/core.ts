// The core services, as the Modules page shows them next to the grown modules. They are not in the
// supervisor's registry (compose runs them), so what they are comes from here and whether they are up
// comes from a probe or from the bus.

import type { BusEvent, Json } from "@/lib/schemas";

export interface CoreService {
  name: string;
  purpose: string;
  need: string;
  listens: string[];
  emits: string[];
  answers: string[]; // rpc subjects without the rpc. prefix
  probe: string | null; // an rpc subject that answers when the service is up
  probePayload?: Json;
  evidence?: (e: BusEvent) => boolean; // or: a recent event only this service publishes
  optional?: boolean; // a compose profile, not always running
}

export const CORE: CoreService[] = [
  {
    name: "supervisor",
    purpose: "The only piece with Docker access. Validates manifests, builds and runs modules, reconciles on start.",
    need: "Core service.",
    listens: ["rpc.sys.*"],
    emits: ["sys.module.deployed", "sys.module.stopped", "sys.reconciled"],
    answers: ["sys.list", "sys.deploy", "sys.stop", "sys.logs", "sys.health"],
    probe: "rpc.sys.list",
  },
  {
    name: "tracer",
    purpose:
      "Records every bus message into the Postgres events table and every trace into traces; owns the JetStream EVENTS stream.",
    need: "Core service: the source of truth for memory.",
    listens: [">"],
    emits: [],
    answers: [],
    probe: null,
  },
  {
    name: "memory",
    purpose: "The markdown vault and its index: remember, lookup, recall; the nightly consolidation of the day into notes.",
    need: "Core service.",
    listens: ["rpc.memory.*", "sys.module.deployed"],
    emits: ["trace.consolidate", "trace.rollup"],
    answers: ["memory.remember", "memory.lookup", "memory.recall", "memory.consolidate", "memory.rollup"],
    probe: "rpc.memory.lookup",
    probePayload: { name: "mycelium" },
  },
  {
    name: "gateway",
    purpose: "Every model call goes through here: slots and providers from providers.yaml, shadow mode, the monthly budget.",
    need: "Core service: keys never leave it.",
    listens: ["rpc.llm.*"],
    emits: ["trace.llm"],
    answers: ["llm.complete", "llm.usage", "llm.config"],
    probe: "rpc.llm.usage",
  },
  {
    name: "main",
    purpose: "The judgment: on every message, recall, plan with tools, answer or ask.",
    need: "Core service: everything that decides, nothing that stores.",
    listens: ["sense.chat", "sense.feedback", "brain.observe"],
    emits: ["out.say", "out.ask", "trace.plan", "trace.feedback"],
    answers: [],
    probe: null,
    evidence: (e) => e.subject === "trace.plan" || e.subject === "out.say",
  },
  {
    name: "web",
    purpose: "This app's gateway: the bus over one websocket, your messages in as sense.chat on channel web.",
    need: "Core service.",
    listens: ["out.*", "sense.*", "mod.*", "sys.*", "build.*", "brain.*", "trace.*"],
    emits: ["sense.chat", "sense.feedback"],
    answers: [],
    probe: null,
    evidence: () => true, // you are reading this through it
  },
  {
    name: "telegram",
    purpose: "Your phone on the bus: messages in become sense.chat, out.say and out.notify go back, out.ask as buttons.",
    need: "Core service, optional (compose profile telegram).",
    listens: ["out.say", "out.ask", "out.notify"],
    emits: ["sense.chat", "sense.feedback"],
    answers: [],
    probe: null,
    evidence: (e) => e.data.channel === "telegram" || e.data.source === "telegram",
    optional: true,
  },
];

export const isCore = (name: string) => CORE.some((c) => c.name === name);
