# mycelium

A personal assistant that grows. It watches what you do, remembers it, and when it notices
something it can't handle yet, it **builds itself a new module** — a small service with its own
data and event hooks — and plugs it into the same bus as everything else.

> Status: week 1 skeleton plus memory v1. Bus, event log, supervisor, module SDK + contract, one
> example module, the builder, and the memory service (markdown vault + index + recall, see
> `docs/MEMORY.md`). The brain (Jev gate + planner) and perception come next. Design docs live in
> `docs/`: `VISION.md`, `ARCHITECTURE.md`, `MEMORY.md`.

## How it fits together

```
 inputs (chat, voice, screen, cam, IoT)
            │ sense.*
            ▼
 ┌────────────────────── NATS + JetStream ──────────────────────┐
 │ events: sense.> brain.> mod.> sys.> build.> out.> trace.>    │
 │ requests: rpc.sys.* rpc.mod.<name>.* rpc.memory.*           │
 └──┬──────────────┬──────────────┬──────────────┬─────────────┘
    │              │              │              │
  brain*        memory*       supervisor      modules (generated)
 (Jev+LLM)    (pg + vault)   (owns Docker)    mod.<name>.*, brain.observe
    │                            ▲
    └── build.request ──► builder (Claude Agent SDK, sandboxed) ──► modules/<name>/
                                                     * = not in this skeleton yet
```

| Piece | Where | What it does |
|---|---|---|
| SDK | `sdk/` | `Module` runtime, bus (`NatsBus`, `InMemoryBus`), manifest validation, subject rules |
| Supervisor | `services/supervisor/` | the only thing with Docker access; validates manifests, builds + runs modules, reconciles on start |
| Tracer | `services/tracer/` | records every bus message into Postgres `events`, owns the JetStream `EVENTS` stream |
| Telegram | `services/telegram/` | your phone ↔ `sense.chat` / `out.notify` (optional profile) |
| Template | `template/` | what every new module starts from, incl. **`CONTRACT.md`** (the builder's rulebook) |
| Example | `modules/hello/` | reference module: counts chat messages, answers `stats` |
| Builder | `builder/` | spec → module via Claude Agent SDK, then independent test verification |

### Subjects

- **Events** go in the JetStream stream (replayable): `sense.*`, `brain.observe`, `mod.<name>.<event>`,
  `sys.*`, `build.*`, `out.*`, `trace.*`
- **Requests** live under `rpc.*` and are deliberately *not* in the stream — otherwise JetStream answers
  them with a PubAck before the real responder does.

## Quick start

```bash
cp .env.example .env            # set POSTGRES_PASSWORD at least
make venv                       # local tools: sdk, pytest, ruff
make up                         # nats, postgres, tracer, supervisor, memory
make deploy-hello               # supervisor builds + starts modules/hello
.venv/bin/python scripts/mctl.py pub sense.chat '{"text":"hi"}'
.venv/bin/python scripts/mctl.py ask hello stats
.venv/bin/python scripts/mctl.py list
.venv/bin/python scripts/mctl.py remember mei "moving to Tainan in December" --type person --alias 小美
.venv/bin/python scripts/mctl.py recall "what did 小美 say about Tainan?"
```

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
| `make test-unit` | nothing | SDK, manifest rules, module runtime, supervisor logic (fake Docker), tracer, scaffolding |
| `make test-modules` | nothing | every `modules/*/tests` in isolation + a freshly scaffolded template |
| `make test-integration` | NATS + Postgres | real bus, real module over the wire, JetStream stream, registry, tracer |
| `make test-e2e` | `make up` | the deployed system |

## Layout

```
sdk/                 mycelium_sdk package + module base image Dockerfile
services/            supervisor, tracer, telegram
services/memory/     vault (markdown notes) + Postgres index + recall; rpc.memory.*
template/            new-module template + CONTRACT.md
modules/             deployed modules (hello is hand-written, the rest get generated)
builder/             spec -> module via Claude Agent SDK
specs/               needs written as specs (the builder's input)
db/init.sql          events, modules, traces
tests/               unit, integration, e2e
scripts/             mctl (CLI), new_module, test_modules, setup_github
```
