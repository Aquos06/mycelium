// Fixtures, so the app runs with no gateway (NEXT_PUBLIC_MOCK=1) and so Playwright has a stable world.
//
// **Nothing outside `lib/api/*`'s `mock:` thunks, `lib/bus.tsx` and `__tests__` may import this**: every
// one of those is a lazy `await import("@/lib/mock")`, which keeps the fixtures out of the real bundle.
// A design law pins it.
//
// The world: Hansen's stack an hour into an evening. One grown module running (hello), one growing
// (budget), one paused (garden); a telegram turn that happened earlier, a question Main asked and
// nobody answered yet, a notification, the nightly consolidation. The bus ticks: hello counts a
// message every few seconds, and a chat turn typed here gets a plan and a reply in under a second.

import { ApiError, getToken, mockLockedRequested, unauthorized } from "@/lib/api/client";
import type { BusEvent, ConfigReply, EventsPage, Health, Json, ListReply, ModuleRow, Reply, Sent, UsageReply } from "@/lib/schemas";

export const MOCK_NAME = "Hansen";
/** What the locked mock gateway accepts (see `mockLockedRequested`). */
export const MOCK_TOKEN = "mycelium";

/** The fixture clock: a fixed instant when NEXT_PUBLIC_MOCK_NOW is set (so relative times never flake). */
export function now(): number {
  const pinned = process.env.NEXT_PUBLIC_MOCK_NOW;
  return pinned ? new Date(pinned).getTime() : Date.now();
}

export function mockLocked(): boolean {
  return mockLockedRequested();
}

/** Open, or locked and holding the right token. The mock's version of the gateway's token gate. */
export function mockAuthorized(): boolean {
  return !mockLocked() || getToken() === MOCK_TOKEN;
}

const minutesAgo = (m: number) => new Date(now() - m * 60_000).toISOString();

let ids = 0;
const id = () => `mock-${(++ids).toString(36).padStart(4, "0")}`;

function env(source: string, cause: string | null = null): Json {
  return { id: id(), ts: new Date(now()).toISOString(), source, cause, hops: 0 };
}

// ---- the bus -------------------------------------------------------------------------------

type Listener = (e: BusEvent) => void;

class MockBus {
  private events: BusEvent[] = [];
  private listeners = new Set<Listener>();
  private seq = 0;
  private ticking: ReturnType<typeof setInterval> | null = null;

  constructor() {
    this.seed();
  }

  all(): BusEvent[] {
    return this.events.slice();
  }

  page(after: number, limit: number): EventsPage {
    const rows = this.events.filter((e) => e.seq > after);
    return { ok: true, seq: this.seq, events: rows.slice(-limit) };
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    if (!this.ticking) this.ticking = setInterval(() => this.tick(), 9_000);
    return () => {
      this.listeners.delete(fn);
      if (this.listeners.size === 0 && this.ticking) {
        clearInterval(this.ticking);
        this.ticking = null;
      }
    };
  }

  publish(subject: string, data: Json, received = new Date(now()).toISOString()): BusEvent {
    const e: BusEvent = { seq: ++this.seq, subject, data, received };
    this.events.push(e);
    for (const l of this.listeners) l(e);
    return e;
  }

  private tick() {
    const count = this.events.filter((e) => e.subject === "mod.hello.message.counted").length + 1;
    this.publish("mod.hello.message.counted", { ...env("hello"), count });
  }

  private seed() {
    const at = (m: number, subject: string, data: Json) => this.publish(subject, data, minutesAgo(m));
    at(58, "sys.reconciled", { ...env("supervisor"), modules: ["hello", "garden"] });
    at(57, "sys.module.deployed", { ...env("supervisor"), name: "hello", image: "mycelium/mod-hello:dev" });
    at(52, "trace.consolidate", { ...env("memory"), day: "2026-10-25", ok: true, facts: 14 });
    at(44, "mod.hello.message.counted", { ...env("hello"), count: 1 });
    const said = env("telegram");
    at(31, "sense.chat", { ...said, channel: "telegram", thread: "tg-1", text: "dinner with Mei at 7, remind me at 6" });
    at(31, "trace.llm", { ...env("gateway", String(said.id)), slot: "planner", provider: "claude", model: "claude-sonnet-5-5", ok: true, latency_ms: 1840, cost_usd: 0.0031 });
    const reply = env("main", String(said.id));
    at(30, "trace.plan", {
      ...env("main", String(said.id)),
      channel: "telegram",
      thread: "tg-1",
      input: "dinner with Mei at 7, remind me at 6",
      modules: ["hello"],
      tools: [{ name: "memory.remember", ok: true }],
      cost_usd: 0.0031,
      rounds: 1,
      reply_id: reply.id,
      error: null,
      latency_ms: 2210,
    });
    at(30, "out.say", { ...reply, channel: "telegram", thread: "tg-1", text: "Noted: dinner with Mei at 7. I will remind you at 6." });
    at(22, "mod.hello.message.counted", { ...env("hello"), count: 2 });
    at(18, "sys.module.deployed", { ...env("supervisor"), name: "budget", image: null });
    at(12, "out.notify", { ...env("memory"), text: "Yesterday's notes are consolidated: 14 facts, 3 people.", channel: "web" });
    const ask = env("main");
    at(6, "out.ask", { ...ask, channel: "web", thread: "web", text: "Should I keep the Friday reminder for the garden watering?", choices: ["Keep it", "Drop it", "Ask me Friday"], ref: ask.id });
    at(2, "mod.hello.message.counted", { ...env("hello"), count: 3 });
  }
}

export const mockBus = new MockBus();

// ---- the gateway ---------------------------------------------------------------------------

export function mockHealth(): Health {
  if (!mockAuthorized()) {
    unauthorized();
    throw new ApiError(401, "a bearer token is required (WEB_TOKEN)");
  }
  return { ok: true, name: MOCK_NAME, channel: "web", version: "0.1.0", events: mockBus.all().length, clients: 1, auth: mockLocked() };
}

export function mockEventsPage(after: number, limit: number): EventsPage {
  return mockBus.page(after, limit);
}

/** A turn: what you said lands now, the plan and the reply follow in under a second. */
export function mockSendChat(text: string, thread: string): Sent {
  const said = env("web");
  mockBus.publish("sense.chat", { ...said, channel: "web", thread, text });
  setTimeout(() => {
    const reply = env("main", String(said.id));
    const asksForModules = /running|alive|module/i.test(text);
    mockBus.publish("trace.plan", {
      ...env("main", String(said.id)),
      channel: "web",
      thread,
      input: text,
      modules: asksForModules ? ["hello"] : [],
      tools: asksForModules ? [{ name: "sys.list", ok: true }] : [],
      cost_usd: 0.0018,
      rounds: 1,
      reply_id: reply.id,
      error: null,
      latency_ms: 640,
    });
    mockBus.publish("out.say", {
      ...reply,
      channel: "web",
      thread,
      text: asksForModules
        ? "Right now hello is running and counting messages; budget is still building, garden is paused."
        : `Noted: “${text.slice(0, 80)}”. I remember it for you.`,
    });
  }, 700);
  return { ok: true, id: String(said.id), thread };
}

export function mockFeedback(ref: string, thread: string, fields: { answer?: string; vote?: number }): Sent {
  const e = env("web");
  mockBus.publish("sense.feedback", { ...e, channel: "web", thread, ref, ...fields });
  return { ok: true, id: String(e.id), thread };
}

// ---- the supervisor and the model gateway ----------------------------------------------------

const manifest = (name: string, purpose: string, need: string, more: Partial<ModuleRow["manifest"]> = {}): ModuleRow["manifest"] => ({
  name,
  version: "0.1.0",
  purpose,
  need,
  subscribes: ["sense.chat"],
  emits: ["message.counted"],
  requests: ["stats"],
  hooks: { interval_seconds: [] },
  permissions: { network: false, actuation: false },
  resources: { memory_mb: 128, cpus: 0.5 },
  ...more,
});

export function mockModules(): ModuleRow[] {
  return [
    {
      name: "hello",
      version: "0.1.0",
      status: "running",
      image: "mycelium/mod-hello:dev",
      container: "running",
      manifest: manifest("hello", "Counts every message it sees and says hello back when asked.", "The example module: proves the bus, the manifest and the supervisor end to end."),
    },
    {
      name: "budget",
      version: "0.2.0",
      status: "building",
      image: null,
      container: null,
      manifest: manifest("budget", "Keeps a running total of what you log as spent and answers how the month looks.", "Hansen logs spending in chat; nobody adds it up.", {
        subscribes: ["sense.chat", "brain.observe"],
        emits: ["total.updated", "limit.near"],
        requests: ["month", "add"],
        hooks: { interval_seconds: [86400] },
      }),
    },
    {
      name: "garden",
      version: "0.1.0",
      status: "stopped",
      image: "mycelium/mod-garden:dev",
      container: "exited",
      manifest: manifest("garden", "Waters the balcony on a schedule and tells you when the tank is low.", "The plants died twice in August.", {
        subscribes: ["sense.iot"],
        emits: ["watered", "tank.low"],
        requests: ["status", "water"],
        hooks: { interval_seconds: [21600] },
        permissions: { network: true, actuation: true },
      }),
    },
  ];
}

export function mockConfig(): ConfigReply {
  return {
    ok: true,
    budget_usd_month: 20,
    slots: {
      planner: {
        task: "complete",
        active: "claude",
        shadow: "vllm",
        providers: {
          claude: { kind: "claude", model: "claude-sonnet-5-5", endpoint: null, key_env: "ANTHROPIC_API_KEY", key_state: "ok", max_tokens: 2048, price_in_per_m: 3, price_out_per_m: 15 },
          vllm: { kind: "vllm", model: "/model", endpoint: "http://192.168.0.107:8000/v1", key_env: null, key_state: "not-needed", max_tokens: 2048, price_in_per_m: 0, price_out_per_m: 0 },
          openai: { kind: "openai", model: "gpt-5-mini", endpoint: "https://api.openai.com/v1", key_env: "OPENAI_API_KEY", key_state: "missing", max_tokens: 2048, price_in_per_m: 0.25, price_out_per_m: 2 },
        },
      },
      consolidate: {
        task: "complete",
        active: "vllm",
        shadow: null,
        providers: {
          vllm: { kind: "vllm", model: "/model", endpoint: "http://192.168.0.107:8000/v1", key_env: null, key_state: "not-needed", max_tokens: 4096, price_in_per_m: 0, price_out_per_m: 0 },
        },
      },
      embed: {
        task: "embed",
        active: "tei",
        shadow: null,
        providers: {
          tei: { kind: "tei", model: "BAAI/bge-m3", endpoint: "http://192.168.0.107:8101/v1", key_env: null, key_state: "not-needed", max_tokens: 0, price_in_per_m: 0, price_out_per_m: 0 },
        },
      },
    },
  };
}

export function mockUsage(): UsageReply {
  return { ok: true, month: "2026-10", usd: 4.37, calls: 212, input_tokens: 812_400, output_tokens: 96_300, budget_usd_month: 20 };
}

/** Any rpc subject, answered the way its service would. */
export function mockRpc(subject: string, payload: Json): Reply {
  switch (true) {
    case subject === "rpc.sys.list":
      return { ok: true, modules: mockModules() } satisfies ListReply;
    case subject === "rpc.sys.health":
      return { ok: true, modules: { hello: { ok: true, status: "ok" }, garden: { ok: false, status: "exited" } } };
    case subject === "rpc.sys.logs":
      return { ok: true, name: String(payload.name), logs: `[hello] subscribed sense.chat\n[hello] counted 3 messages\n[hello] health ok` };
    case subject === "rpc.sys.deploy" || subject === "rpc.sys.stop": {
      const action = subject.endsWith("deploy") ? "deployed" : "stopped";
      setTimeout(() => mockBus.publish(`sys.module.${action}`, { ...env("supervisor"), name: String(payload.name) }), 300);
      return { ok: true };
    }
    case subject === "rpc.llm.config":
      return mockConfig();
    case subject === "rpc.llm.usage":
      return mockUsage();
    case subject === "rpc.memory.lookup":
      return { ok: true, name: String(payload.name), notes: [] };
    case subject.startsWith("rpc.mod."): {
      const [, , name, action] = subject.split(".");
      if (action === "health") return { ok: true, status: "ok" };
      if (action === "stats") return { ok: true, name, counted: 3, since: minutesAgo(58) };
      return { ok: true, name, action, echo: payload };
    }
    default:
      return { ok: false, error: `no responder for ${subject}` };
  }
}
