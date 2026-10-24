# mycelium

A personal assistant that grows. It watches what you do, remembers it, and when it notices
something it can't handle yet, it **builds itself a new module** — a small service with its own
data and event hooks — and plugs it into the same bus as everything else.

> Status: the chatbot core works end to end. Bus, event log, supervisor, module SDK + contract, one
> example module, the builder, the memory service (markdown vault + index + recall, `docs/MEMORY.md`),
> the model gateway (Claude, OpenAI, Ollama, vLLM and more behind one slot config), Main v0
> (recall → plan with tools → reply, threads in NATS KV, a trace per answer) and nightly memory
> consolidation (a day of events → day summary, dated facts, new notes). Next: the gate and state
> snapshot in Main, embeddings and rollups (M4), perception. Design docs live in `docs/`:
> `VISION.md`, `ARCHITECTURE.md`, `MEMORY.md`.

## How it fits together

```
 inputs (chat, voice, screen, cam, IoT)            channels: telegram, cli (web app later)
            │ sense.*                                   ▲ out.say / out.ask / out.notify
            ▼                                           │
 ┌────────────────────── NATS + JetStream ────────────────────────────┐
 │ events: sense.> brain.> mod.> sys.> build.> out.> trace.>          │
 │ requests: rpc.sys.* rpc.mod.<name>.* rpc.memory.* rpc.llm.*       │
 └──┬──────────────┬──────────────┬──────────────┬──────────────┬────┘
    │              │              │              │              │
  main          memory        gateway       supervisor      modules (generated)
 (planner)    (pg + vault)   (model keys)   (owns Docker)    mod.<name>.*, brain.observe
    │                                           ▲
    └── build.request ──► builder (Claude Agent SDK, sandboxed) ──► modules/<name>/
```

| Piece | Where | What it does |
|---|---|---|
| SDK | `sdk/` | `Module` runtime, bus (`NatsBus`, `InMemoryBus`), KV (`NatsKV`, `InMemoryKV`), envelope, manifest validation, subject rules |
| Supervisor | `services/supervisor/` | the only thing with Docker access; validates manifests, builds + runs modules, reconciles on start |
| Tracer | `services/tracer/` | records every bus message into Postgres `events` and every `trace.*` into `traces`; owns the JetStream `EVENTS` stream |
| Memory | `services/memory/` | markdown vault (the truth) + Postgres index + recall; `rpc.memory.*` |
| Gateway | `services/gateway/` | `rpc.llm.complete` behind slots and providers (`providers.yaml`): Claude, OpenAI, Ollama, vLLM, OpenRouter, Groq, DeepSeek, Mistral, Gemini, xAI or any OpenAI-compatible endpoint; shadow mode, monthly budget, `trace.llm` |
| Main | `services/main/` | on `sense.chat`: recall pack + thread → planner with tools (`remember`, `recall`, `ask_module`, `ask`) → `out.say` / `out.ask` + `trace.plan` |
| Telegram | `services/telegram/` | your phone ↔ `sense.chat` / `out.say`; `out.ask` as buttons, taps back as `sense.feedback` (optional profile) |
| Template | `template/` | what every new module starts from, incl. **`CONTRACT.md`** (the builder's rulebook) |
| Example | `modules/hello/` | reference module: counts chat messages, answers `stats` |
| Builder | `builder/` | spec → module via Claude Agent SDK, then independent test verification |

### Subjects

- **Events** go in the JetStream stream (replayable): `sense.*`, `brain.observe`, `mod.<name>.<event>`,
  `sys.*`, `build.*`, `out.*`, `trace.*`
- **Requests** live under `rpc.*` and are deliberately *not* in the stream — otherwise JetStream answers
  them with a PubAck before the real responder does. `rpc.sys.*` supervisor, `rpc.mod.<name>.*` modules,
  `rpc.memory.*` memory, `rpc.llm.*` gateway.

## Quick start

```bash
cp .env.example .env            # set POSTGRES_PASSWORD; ANTHROPIC_API_KEY for the planner and builder
make venv                       # local tools: sdk, pytest, ruff
make up                         # nats, postgres, tracer, supervisor, memory, gateway, main
make deploy-hello               # supervisor builds + starts modules/hello
.venv/bin/python scripts/mctl.py chat "remember that 小美 is moving to Tainan in December"
.venv/bin/python scripts/mctl.py chat "what did 小美 tell me?"
.venv/bin/python scripts/mctl.py usage                      # gateway spend this month
.venv/bin/python scripts/mctl.py ask hello stats
.venv/bin/python scripts/mctl.py list
.venv/bin/python scripts/mctl.py remember mei "moving to Tainan in December" --type person --alias 小美
.venv/bin/python scripts/mctl.py recall "what did 小美 say about Tainan?"
.venv/bin/python scripts/mctl.py consolidate 2026-10-14                   # (re)run the nightly consolidation for a day
.venv/bin/python scripts/mctl.py rollup 2026-W42                          # (re)write a week or month summary from its days
```

Without `ANTHROPIC_API_KEY`, `chat` still works end to end but Main answers that it cannot reach its
model; the message and a `trace.plan` with the error are recorded. To run a local model instead,
`make local` (starts Ollama next to the stack and pulls `qwen2.5:14b`) and set `planner.active: ollama`
in `services/gateway/providers.yaml`; on a GPU box `docker compose --profile gpu up -d vllm` and `vllm`.
Any other vendor is a `kind` (`openai`, `openrouter`, `groq`, `deepseek`, `mistral`, `gemini`, `xai`,
or `openai_compat` with an `endpoint`) plus its key in `.env`.

Grow a module from a spec (needs `ANTHROPIC_API_KEY` in `.env`):

```bash
make build-module NAME=expenses SPEC=specs/expenses.md
.venv/bin/python scripts/mctl.py deploy expenses
```

Phone: create a bot with @BotFather, put `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` in `.env`,
then `docker compose --profile telegram up -d`.

## Safety rails (enforced in code, not just docs)

- Only the supervisor mounts the Docker socket. The builder only sees `modules/`, `template/`, `specs/`.
- Modules run on an **internal** network (bus only, no internet) unless `permissions.network: true`.
- `permissions.actuation: true` modules refuse to deploy until listed in `APPROVED_ACTUATORS`.
- The SDK raises `ContractViolation` for any subscribe / emit / request / interval not declared in the manifest.
- Manifests can't subscribe to `>`, `rpc.*`, `_INBOX` or their own events (loops).
- Each module gets its own volume, memory and CPU limit.

## Branches, CI and CD

```
feature/* ──PR──► dev ──PR──► stage ──PR──► main
                   │           │            │
             development    staging     production (needs approval)
```

- **ci.yml** (every PR): `lint` → `unit` (+ each module's own tests + template smoke) →
  `integration` (real NATS with JetStream + pgvector Postgres) → `e2e` (whole compose stack:
  supervisor builds and runs `hello`, events flow, tracer records them).
- **cd.yml** (every push to dev/stage/main): reruns CI, pushes images to GHCR
  (`ghcr.io/<owner>/<repo>/<image>:<branch>` and `:sha-xxxxxxx`), then deploys to the matching
  environment on your self-hosted runner. The new supervisor reconciles on start, so every running
  module is rebuilt from the new commit.
- dev, staging and production can share one box: everything is namespaced by `STACK`
  (containers, networks, volumes, module images) and ports come from environment variables.

One-time setup after the first push:

```bash
gh auth login
./scripts/setup_github.sh <owner>/<repo>   # branches, protection, environments + their variables
```

then add environment secrets, register a self-hosted runner labelled `mycelium`, and set
`DEPLOY_ENABLED=true`. Until then CD stops after pushing images.

## Tests

| Command | Needs | Covers |
|---|---|---|
| `make test-unit` | nothing | SDK, manifest rules, module runtime, supervisor logic (fake Docker), tracer, scaffolding, memory (fixture vault + events, consolidation with a scripted model), gateway (fake providers), Main (scripted planner), Telegram (fake API) |
| `make test-modules` | nothing | every `modules/*/tests` in isolation + a freshly scaffolded template |
| `make test-integration` | NATS + Postgres | real bus, real module over the wire, JetStream stream and KV, registry, tracer, memory index + recall on Postgres |
| `make test-e2e` | `make up` | the deployed system |

## Layout

```
sdk/                 mycelium_sdk package + module base image Dockerfile
services/            supervisor, tracer, telegram
services/memory/     vault (markdown notes) + index + recall + nightly consolidation; rpc.memory.*: schemas/, index/, events/ like the gateway
services/gateway/    model gateway; rpc.llm.*: schemas/ (config, wire shapes, usage, traces), providers/ (claude, openai_compat), service.py
services/main/       the planner: thread (KV) + recall pack -> tools/ (pydantic args + handler each) -> out.say / out.ask, trace.plan
template/            new-module template + CONTRACT.md
modules/             deployed modules (hello is hand-written, the rest get generated)
builder/             spec -> module via Claude Agent SDK
specs/               needs written as specs (the builder's input)
sdk/mycelium_sdk/db/ SQLAlchemy async engine + Alembic runner; the core tables (events, modules, traces) and their migrations
tests/               unit, integration, e2e
scripts/             mctl (CLI), new_module, test_modules, setup_github
```
