// The transport for every call in this folder. Nothing here knows an endpoint.
//
// One request: mock → token → status → parse. Throws on failure, deliberately: TanStack Query drives
// `isError` off a thrown error and `query-provider.tsx::retry` reads the status off `ApiError`.

/** Where the browser reaches the web gateway. Unset in a production build it is "" (same origin: Caddy in
 *  front routes /api to the gateway and the rest here); `pnpm dev` defaults to the gateway on :8080. */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? (process.env.NODE_ENV === "development" ? "http://localhost:8080" : "");
export const API = "/api/v1";

/** Demo mode: every call answers from fixtures (lib/mock) and the bus is a timer. No gateway needed. */
export const MOCK = process.env.NEXT_PUBLIC_MOCK === "1";

/** `NEXT_PUBLIC_MOCK_LOCKED=1`, or the same key in localStorage, makes the mock gateway ask for a token,
 *  so the login screen is reachable without a real WEB_TOKEN. Read at runtime for the reason the flag
 *  exists: NEXT_PUBLIC_* is baked at build time and the e2e suite runs one build. */
const MOCK_LOCKED_KEY = "mycelium.mock.locked";

export function mockLockedRequested(): boolean {
  if (process.env.NEXT_PUBLIC_MOCK_LOCKED === "1") return true;
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(MOCK_LOCKED_KEY) === "1";
  } catch {
    return false;
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** One sentence for a failed call: "<who> is not answering" when nobody on the bus replied (the gateway's
 *  504), the error's own words otherwise. Keyed on the status, not the message, so a reworded 504 cannot
 *  break it. */
export function describeError(e: unknown, who: string): string {
  if (e instanceof ApiError && e.status === 504) return `${who} is not answering`;
  return e instanceof Error ? e.message : String(e);
}

// ---- the token ----------------------------------------------------------------------------
// One bearer token (WEB_TOKEN on the gateway), kept in localStorage and mirrored in memory for SSR.
const TOKEN_KEY = "mycelium.token";
let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function getToken(): string | null {
  if (token === null && typeof window !== "undefined") {
    try {
      token = window.localStorage.getItem(TOKEN_KEY);
    } catch {
      /* a private window refuses storage: in-memory only */
    }
  }
  return token;
}

export function setToken(value: string | null): void {
  token = value;
  if (typeof window === "undefined") return;
  try {
    if (value) window.localStorage.setItem(TOKEN_KEY, value);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* best effort; the in-memory token still works this session */
  }
}

/** The auth gate registers here, so a 401 anywhere sends the app to the login screen. */
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

export function unauthorized(): void {
  onUnauthorized?.();
}

/** The socket's address, from the same base as the REST calls. No token in it: a URL ends up in every access
 *  log in front of the gateway, so the token rides as a subprotocol instead (`socketProtocols`). */
export function socketUrl(): string {
  const base = API_BASE
    ? API_BASE.replace(/^http/, "ws")
    : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
  return `${base}${API}/events/ws`;
}

/** The one header a browser lets a WebSocket set is Sec-WebSocket-Protocol, so the token goes there:
 *  `bearer, <base64url token>` (base64url because a subprotocol may not contain `=`, `/` or spaces). The
 *  gateway answers `bearer` (services/web/events/router.py). Empty without a token. */
export function socketProtocols(): string[] {
  const t = getToken();
  if (!t) return [];
  const bytes = new TextEncoder().encode(t);
  const b64 = btoa(String.fromCharCode(...bytes));
  return ["bearer", b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")];
}

// ---- response handling --------------------------------------------------------------------

/** The structural slice of a zod schema `parsed` needs. */
export interface Parser<T> {
  safeParse(v: unknown):
    | { success: true; data: T }
    | { success: false; error: { issues: { path: PropertyKey[]; message: string }[] } };
}

/** Throws rather than repairing with defaults: a defaulted number is a plausible lie on a page that
 *  promises real ones, and every screen can already render an error. */
export function parsed<T>(schema: Parser<T>, value: unknown, what: string): T {
  const out = schema.safeParse(value);
  if (out.success) return out.data;
  const where = out.error.issues
    .slice(0, 3)
    .map((i) => `${i.path.map(String).join(".") || "(root)"}: ${i.message}`)
    .join("; ");
  throw new Error(`${what}: unexpected response from the gateway — ${where}`);
}

function delay<T>(value: T, ms: number): Promise<T> {
  return new Promise((r) => setTimeout(() => r(value), ms));
}

export interface FetchOptions<T> {
  method?: "GET" | "POST";
  body?: unknown;
  /** `what` names the subject in the error, so a schema cannot travel without one. */
  parse?: { schema: Parser<T>; what: string };
  /** A thunk, not a value, so `await import("@/lib/mock")` stays lazy and out of the real bundle. */
  mock?: () => Promise<T> | T;
  mockDelay?: number;
}

export async function apiFetch<T>(path: string, opts: FetchOptions<T> = {}): Promise<T> {
  if (MOCK && opts.mock) return delay(await opts.mock(), opts.mockDelay ?? 120);

  const headers: Record<string, string> = {};
  const t = getToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method ?? "GET",
    headers,
    cache: "no-store",
    ...(opts.body !== undefined ? { body: JSON.stringify(opts.body) } : {}),
  });

  if (!res.ok) {
    let error = `API ${res.status}: ${res.statusText}`;
    try {
      const j = (await res.json()) as { error?: unknown };
      if (typeof j.error === "string") error = j.error;
    } catch {
      /* a non-JSON refusal: keep the status line */
    }
    if (res.status === 401) unauthorized();
    throw new ApiError(res.status, error);
  }

  const body: unknown = await res.json();
  return opts.parse ? parsed(opts.parse.schema, body, opts.parse.what) : (body as T);
}
