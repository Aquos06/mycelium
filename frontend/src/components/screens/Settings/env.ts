// What each settings tab describes: the environment a service reads at start. Read-only for now, so
// this is the vocabulary, not the values (they are in the stack's .env and never cross the bus).

import type { SettingsTab } from "@/lib/nav";

export const TABS: { id: SettingsTab; label: string; svc: string }[] = [
  { id: "models", label: "Models", svc: "gateway" },
  { id: "keys", label: "API keys", svc: ".env secrets" },
  { id: "builder", label: "Builder", svc: "builder" },
  { id: "memory", label: "Memory", svc: "memory" },
  { id: "assistant", label: "Assistant", svc: "main" },
  { id: "system", label: "System", svc: "all services" },
  { id: "web", label: "This app", svc: "web" },
];

export const KIND_NAMES: Record<string, string> = {
  claude: "Anthropic",
  openai: "OpenAI",
  ollama: "Ollama",
  vllm: "vLLM",
  tei: "TEI",
  openrouter: "OpenRouter",
  groq: "Groq",
  deepseek: "DeepSeek",
  mistral: "Mistral",
  gemini: "Gemini",
  xai: "xAI",
  openai_compat: "OpenAI-compatible",
};

export const SLOT_WORDS: Record<string, [string, string]> = {
  planner: ["Planner", "Answers you and decides what to do next. One call per planner round."],
  consolidate: ["Consolidation", "Memory's nightly job: one structured call per day, so a cheap model."],
  embed: ["Embeddings", "Turns notes and summaries into vectors for memory's fuzzy recall."],
  decide: ["Rerank", "Scores recall candidates in the decide step."],
  coder: ["Coder", "The builder's own coder writes modules through this slot, when it is the one chosen in Settings → Builder."],
};

export interface EnvRow {
  label: string;
  desc: string;
  env: string;
  value?: string;
  unit?: string;
}

export const ENV: Partial<Record<SettingsTab, { title: string; desc: string; rows: EnvRow[] }>> = {
  builder: {
    title: "Set at start",
    desc: "Read when they start: the builder (its coder, its agents, the limits), the supervisor (the agents' model) and the gateway (our coder's model).",
    rows: [
      { label: "First default", desc: "The coder until one is chosen above.", env: "BUILDER_CODER" },
      { label: "Coding agents", desc: "Which agents the builder offers.", env: "BUILDER_AGENTS" },
      { label: "Our coder's model", desc: "Which provider the gateway's coder slot uses (Models). Read by the gateway.", env: "CODER_PROVIDER" },
      { label: "Agents' model", desc: "An OpenAI-compatible address the agents' containers reach: the GPU box by IP, not a compose name.", env: "AGENT_ENDPOINT" },
      { label: "Agents' model name", desc: "The model the agents ask for there.", env: "AGENT_MODEL" },
      { label: "Rounds", desc: "Coder, checks and the sealed tests, at most this many times.", env: "BUILD_MAX_ROUNDS", unit: "rounds" },
      { label: "Whole build", desc: "A build that takes longer fails where it was.", env: "BUILD_TIMEOUT", unit: "sec" },
    ],
  },
  memory: {
    title: "Memory",
    desc: "Where memory keeps its vault and when it consolidates the day into notes. Read by services/memory at start.",
    rows: [
      { label: "Timezone", desc: "Local day boundaries: what “yesterday” means.", env: "MEMORY_TZ" },
      { label: "Nightly consolidation", desc: "Local time memory rolls the day up into notes. Empty: off, mctl consolidate still works.", env: "MEMORY_CONSOLIDATE_AT" },
      { label: "Vault", desc: "The markdown notes: people, places, projects, summaries.", env: "MEMORY_VAULT_DIR" },
      { label: "Schema", desc: "Memory's tables inside its database.", env: "MEMORY_SCHEMA" },
      { label: "Database", desc: "Memory's own database when it has one, else the shared one.", env: "MEMORY_DATABASE_URL" },
    ],
  },
  assistant: {
    title: "Assistant",
    desc: "How Main holds a conversation. Read by services/main at start.",
    rows: [
      { label: "Timezone", desc: "What “today” means in the prompt.", env: "MAIN_TZ" },
      { label: "Thread memory", desc: "Turns kept per thread in KV.", env: "MAIN_MAX_TURNS", unit: "turns" },
      { label: "Model timeout", desc: "Seconds per planner round. Raise it for a cold local model.", env: "MAIN_LLM_TIMEOUT", unit: "sec" },
      { label: "Currency", desc: "Money in the tables and charts Main shows (an ISO code).", env: "MAIN_CURRENCY" },
    ],
  },
  system: {
    title: "System",
    desc: "Shared by every service. Read once at start.",
    rows: [
      { label: "Bus", desc: "The NATS server every service connects to.", env: "NATS_URL" },
      { label: "Log level", desc: "How chatty the services are: DEBUG, INFO, WARNING, ERROR.", env: "LOG_LEVEL" },
      { label: "Stack", desc: "Namespaces containers, networks and volumes, so dev and production share one host.", env: "STACK" },
      { label: "Gateway config", desc: "The providers.yaml the Models tab reads.", env: "GATEWAY_CONFIG" },
    ],
  },
};
