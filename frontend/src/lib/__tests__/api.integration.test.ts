import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  API_BASE,
  ApiError,
  askModule,
  describeError,
  fetchEvents,
  fetchHealth,
  getToken,
  rpc,
  sendChat,
  sendFeedback,
  setToken,
  setUnauthorizedHandler,
  socketProtocols,
  socketUrl,
} from "@/lib/api";

// The request contract against the web gateway (services/web): URL, method, bearer, body, the error
// envelope, the 401 hook. fetch is stubbed, so this runs with no gateway. MOCK is off here.

function json(body: unknown, status = 200): Response {
  return { ok: status < 400, status, statusText: status === 200 ? "OK" : "Nope", json: async () => body } as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  setToken(null);
  setUnauthorizedHandler(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the transport", () => {
  it("GETs health from the versioned API and parses it", async () => {
    fetchMock.mockResolvedValueOnce(json({ ok: true, name: "Hansen", channel: "web", version: "0.1.0", events: 0, clients: 0, auth: false }));
    const h = await fetchHealth();
    expect(h.name).toBe("Hansen");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE}/api/v1/system/health`);
    expect(init.method).toBe("GET");
    expect(init.headers.Authorization).toBeUndefined();
  });

  it("carries the token as a bearer, and on the socket as a subprotocol rather than in the URL", async () => {
    setToken("s3cret");
    expect(getToken()).toBe("s3cret");
    fetchMock.mockResolvedValueOnce(json({ ok: true, seq: 0, events: [] }));
    await fetchEvents(7, 50);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE}/api/v1/events?after=7&limit=50`);
    expect(init.headers.Authorization).toBe("Bearer s3cret");
    // outside `pnpm dev` the base is "" (same origin), so the socket follows the page's own host
    const wsBase = API_BASE ? API_BASE.replace(/^http/, "ws") : `ws://${window.location.host}`;
    expect(socketUrl()).toBe(`${wsBase}/api/v1/events/ws`);
    expect(socketUrl()).not.toContain("s3cret");
    expect(socketProtocols()).toEqual(["bearer", "czNjcmV0"]); // base64url("s3cret"), no padding
    setToken("pad/me+now=");
    expect(socketProtocols()[1]).toMatch(/^[A-Za-z0-9_-]+$/); // nothing a subprotocol may not carry
    setToken(null);
    expect(socketProtocols()).toEqual([]);
  });

  it("describes a 504 as the responder not answering, and anything else in its own words", () => {
    expect(describeError(new ApiError(504, "no reply from rpc.sys.list within 5s"), "the supervisor")).toBe("the supervisor is not answering");
    expect(describeError(new ApiError(400, "not an rpc subject"), "the supervisor")).toBe("not an rpc subject");
    expect(describeError("boom", "x")).toBe("boom");
  });

  it("POSTs chat and feedback as JSON", async () => {
    fetchMock.mockResolvedValue(json({ ok: true, id: "e1", thread: "t" }));
    await sendChat("hi", "t");
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE}/api/v1/chat`);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ text: "hi", thread: "t" });
    expect(fetchMock.mock.calls[0][1].headers["Content-Type"]).toBe("application/json");
    await sendFeedback("q1", "t", { answer: "yes" });
    expect(fetchMock.mock.calls[1][0]).toBe(`${API_BASE}/api/v1/chat/feedback`);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ ref: "q1", thread: "t", answer: "yes" });
  });

  it("forwards an rpc with its payload and timeout, and hands back a refusal as data", async () => {
    fetchMock.mockResolvedValueOnce(json({ ok: false, error: "unknown action" }));
    const r = await askModule("hello", "nope", { a: 1 });
    expect(r).toEqual({ ok: false, error: "unknown action" });
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE}/api/v1/rpc/rpc.mod.hello.nope`);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ payload: { a: 1 }, timeout: 15 });
  });

  it("throws the gateway's error envelope with its status", async () => {
    fetchMock.mockResolvedValueOnce(json({ ok: false, error: "no reply from rpc.x.y within 5s" }, 504));
    await expect(rpc("rpc.x.y")).rejects.toMatchObject({ status: 504, message: "no reply from rpc.x.y within 5s" });
    fetchMock.mockResolvedValueOnce({ ok: false, status: 502, statusText: "Bad Gateway", json: async () => ({}) } as Response);
    await expect(rpc("rpc.x.y")).rejects.toMatchObject({ status: 502, message: "API 502: Bad Gateway" });
  });

  it("a 401 fires the unauthorized hook and throws", async () => {
    const hook = vi.fn();
    setUnauthorizedHandler(hook);
    fetchMock.mockResolvedValueOnce(json({ ok: false, error: "a bearer token is required (WEB_TOKEN)" }, 401));
    await expect(fetchHealth()).rejects.toBeInstanceOf(ApiError);
    expect(hook).toHaveBeenCalledOnce();
  });

  it("refuses a response that does not match the schema, naming the field", async () => {
    fetchMock.mockResolvedValueOnce(json({ ok: true, name: "Hansen" }));
    await expect(fetchHealth()).rejects.toThrow(/the gateway's health: unexpected response .* channel/);
  });
});
