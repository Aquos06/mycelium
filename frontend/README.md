# mycelium — the app

Next.js 16 · Tailwind v4 · shadcn-style primitives on Base UI · TanStack Query · zod · pnpm.
Paper, not chrome. Colour means a place on the bus. Motion only for real activity.

The app talks to one service, the web gateway (`services/web`, ARCHITECTURE §10): REST under `/api/v1`
for what you say and ask, one websocket for everything the bus says back. Nothing in the UI is faked:
every number comes from the bus or an `rpc.*` reply.

> **Read [`AGENTS.md`](AGENTS.md) before editing.** This is Next.js **16**; the bundled guides in
> `node_modules/next/dist/docs/` are the reference.

## Getting started

**pnpm** and Node 22 (what CI and the image run).

```bash
pnpm install
pnpm dev                        # → http://localhost:3000, against the gateway on :8080 (make up)
NEXT_PUBLIC_MOCK=1 pnpm dev     # no gateway: every screen from fixtures, the bus is a timer
```

## Configuration

`NEXT_PUBLIC_*` is read from `frontend/.env.local` (git-ignored) and **baked into the bundle at build time**.

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8080` in `pnpm dev`, the page's own origin in a build | Where the browser reaches the web gateway (REST and the socket) |
| `NEXT_PUBLIC_MOCK` | `0` | `1` serves every screen from `src/lib/mock` |
| `NEXT_PUBLIC_MOCK_NOW` | — | Freezes the fixture clock |

A production build without `NEXT_PUBLIC_API_BASE` calls its own origin: the deployment this app is for
is Caddy in front, `/api` to the gateway and the rest here, with no CORS at all. The compose dev stack
sets it to the gateway's port instead (`PUBLIC_API_BASE` in the stack's `.env`, a `--build-arg` in
`Dockerfile`), and then the gateway must list this app's origin in `WEB_CORS_ORIGINS` (it does for
`localhost:3000` by default). The gateway asks for `WEB_TOKEN` when one is set: the app keeps it in
`localStorage` and sends it as a bearer.

## Layout

```
src/app/            routes: (app) behind the token gate, (public)/login outside it
src/components/
  ui/               shared primitives: Button, Pill, Chip, Spark, Composer, Shell, Sidebar, TabBar, Topbar
  screens/          one folder per screen: Home, Chat, Modules, ModuleDetail, Settings, Voice, Login
src/lib/
  api/              the ONLY place that touches the network, split by gateway domain
  queries/          TanStack Query hooks over lib/api; components call these, never lib/api
  schemas/          zod for what the gateway SENDS, mirroring its pydantic models; types are z.infer
  mock/             the fixtures, imported only lazily from lib/api's `mock:` thunks and lib/bus.tsx
  bus.tsx           the websocket as React state; chat.ts a conversation from the bus; domains.ts the readings
```

Import the **barrel** (`@/lib/api`, `@/lib/queries`, `@/lib/schemas`), never a file inside it.

## Testing

Three layers; the rule is **a unit test for every helper, an integration test for every call and screen,
an e2e test for every UI surface**. Vitest files are tagged by name so each CI stage runs its slice.

| Layer | Tool | Filename | Run |
|---|---|---|---|
| Unit: pure helpers, schemas, the design laws | Vitest (jsdom) | `*.unit.test.ts` | `pnpm test:unit` |
| Integration: the API client, a screen rendered | Vitest + Testing Library | `*.integration.test.{ts,tsx}` | `pnpm test:integration` |
| E2E: the app in a browser, two viewports | Playwright | `e2e/*.spec.ts` | `pnpm test:e2e` |

```bash
pnpm typecheck && pnpm lint     # what CI runs first
pnpm test                       # unit + integration
pnpm test:e2e                   # builds and serves the app in NEXT_PUBLIC_MOCK=1 on :3131, drives Chromium
```

E2E needs the browser once: `pnpm exec playwright install chromium`. `designlaws.unit.test.ts` enforces the
structure above rather than describing it.

## Ship

`docker compose up -d --build frontend` from the repo root builds the image with the stack's
`PUBLIC_API_BASE` and serves it on `127.0.0.1:${FRONTEND_PORT:-3000}`; CD pushes the same image as
`frontend`. Caddy or Tailscale in front of both ports for anything beyond the machine.
