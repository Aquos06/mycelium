import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  process.env.NEXT_PUBLIC_MOCK = "1";
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/chat/web",
}));

import { Chat } from "@/components/screens/Chat";
import { mockBuilds, mockBus } from "@/lib/mock";
import { envelope, event, renderScreen } from "./support";

function aTurn() {
  const u = envelope("u1");
  const a = envelope("a1", "u1");
  const q = envelope("q1");
  return [
    event("sense.chat", { ...u, channel: "web", thread: "web", text: "what is running?" }),
    event("out.say", { ...a, channel: "web", thread: "web", text: "hello is running.\n\nbudget is building." }),
    event("trace.plan", { ...envelope("t1", "u1"), channel: "web", thread: "web", rounds: 1, tools: [{ name: "sys.list" }], cost_usd: 0.002, latency_ms: 640, error: null }),
    event("out.ask", { ...q, channel: "web", thread: "web", text: "Pause garden?", choices: ["Yes", "No"], ref: "q1" }),
    event("sense.chat", { ...envelope("tg"), channel: "telegram", thread: "web", text: "not this channel" }),
  ];
}

describe("Chat", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders a turn in order: you, the plan, the reply, then the question", () => {
    renderScreen(<Chat thread="web" />, aTurn());
    const kinds = [...document.querySelectorAll("[data-kind]")].map((el) => el.getAttribute("data-kind"));
    expect(kinds).toEqual(["user", "trace", "assistant", "ask"]);
    expect(screen.getByText("what is running?")).toBeInTheDocument();
    expect(screen.getByText("Planned with sys.list")).toBeInTheDocument();
    expect(screen.getByText("hello is running.")).toBeInTheDocument();
    expect(screen.getByText("budget is building.")).toBeInTheDocument();
    expect(screen.queryByText("not this channel")).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Pause garden?" })).toBeInTheDocument();
  });

  it("answers a question and votes on a reply through sense.feedback", async () => {
    renderScreen(<Chat thread="web" />, aTurn());
    const before = mockBus.all().filter((e) => e.subject === "sense.feedback").length;
    await userEvent.click(within(screen.getByRole("group", { name: "Pause garden?" })).getByRole("button", { name: "Yes" }));
    await userEvent.click(screen.getByRole("button", { name: "Good answer" }));
    await waitFor(() => {
      const fb = mockBus.all().filter((e) => e.subject === "sense.feedback").slice(before);
      expect(fb.map((e) => [e.data.ref, e.data.answer ?? e.data.vote])).toEqual([
        ["q1", "Yes"],
        ["a1", 1],
      ]);
    });
    expect(screen.getByRole("button", { name: "Good answer" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the reply being written while your last message is unanswered, Planning… before the first piece", () => {
    const u = envelope("u2");
    const mine = [event("sense.chat", { ...u, ts: new Date().toISOString(), channel: "web", thread: "web", text: "what is running?" })];
    const { unmount } = renderScreen(<Chat thread="web" />, mine, "live", {});
    expect(screen.getByRole("status")).toHaveTextContent("Planning…");
    unmount();
    renderScreen(<Chat thread="web" />, mine, "live", { u2: { request: "r1", provider: "claude", text: "hello is run", thinking: "", done: false } });
    const live = screen.getByRole("status", { name: "Main is writing" });
    expect(live).toHaveTextContent("hello is run");
    expect(live).toHaveAttribute("data-kind", "stream");
    expect(screen.queryByText("Planning…")).not.toBeInTheDocument();
  });

  it("shows the thinking in place of Planning…, then folds it away once the reply is being written", async () => {
    const u = envelope("u4");
    const mine = [event("sense.chat", { ...u, ts: new Date().toISOString(), channel: "web", thread: "web", text: "hi" })];
    const { unmount } = renderScreen(<Chat thread="web" />, mine, "live", {
      u4: { request: "r1", provider: "vllm", text: "", thinking: "The user says hi. Keep it short.", done: false },
    });
    const status = screen.getByRole("status", { name: "Main is thinking" });
    expect(status).toHaveTextContent("Thinking…");
    expect(status).not.toHaveTextContent("The user says hi."); // the text is shown, not announced frame by frame
    expect(screen.getByText("The user says hi. Keep it short.")).toHaveAttribute("aria-live", "off");
    expect(screen.queryByText("Planning…")).not.toBeInTheDocument();
    unmount();

    const { restream } = renderScreen(<Chat thread="web" />, mine, "live", {
      u4: { request: "r1", provider: "vllm", text: "Hi!", thinking: "The user says hi. Keep it short.", done: false },
    });
    expect(screen.getByRole("status", { name: "Main is writing" })).toHaveTextContent("Hi!");
    expect(screen.queryByRole("status", { name: "Main is thinking" })).not.toBeInTheDocument();
    expect(screen.queryByText("The user says hi. Keep it short.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show thinking" }));
    expect(screen.getByText("The user says hi. Keep it short.")).toBeInTheDocument();

    // the next planner round thinks again, and once it writes, its thinking is folded, not left open
    restream({ u4: { request: "r2", provider: "vllm", text: "", thinking: "Saved. Now answer.", done: false } });
    expect(screen.getByRole("status", { name: "Main is thinking" })).toBeInTheDocument();
    restream({ u4: { request: "r2", provider: "vllm", text: "Done.", thinking: "Saved. Now answer.", done: false } });
    expect(screen.getByRole("button", { name: "Show thinking" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Saved. Now answer.")).not.toBeInTheDocument();
  });

  it("takes blank lines for nothing: no empty bubble after the thinking, Planning… before any real thought", () => {
    const u = envelope("u5");
    const mine = [event("sense.chat", { ...u, ts: new Date().toISOString(), channel: "web", thread: "web", text: "hi" })];
    const { unmount } = renderScreen(<Chat thread="web" />, mine, "live", {
      u5: { request: "r1", provider: "vllm", text: "\n\n", thinking: "Remember the name first.", done: false },
    });
    expect(screen.getByRole("status", { name: "Main is thinking" })).toBeInTheDocument();
    expect(screen.getByText("Remember the name first.")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Main is writing" })).not.toBeInTheDocument();
    unmount();

    renderScreen(<Chat thread="web" />, mine, "live", { u5: { request: "r1", provider: "vllm", text: "", thinking: "\n", done: false } });
    expect(screen.getByRole("status")).toHaveTextContent("Planning…");
    expect(document.querySelector("[data-kind=thinking]")).toBeNull();
  });

  it("drops the live text once the reply itself is there", () => {
    const u = envelope("u3");
    const a = envelope("a3", "u3");
    const done = [
      event("sense.chat", { ...u, ts: new Date().toISOString(), channel: "web", thread: "web", text: "hi" }),
      event("out.say", { ...a, ts: new Date().toISOString(), channel: "web", thread: "web", text: "Hello there." }),
    ];
    renderScreen(<Chat thread="web" />, done, "live", { u3: { request: "r1", provider: "claude", text: "Hello th", thinking: "", done: true } });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("Hello there.")).toBeInTheDocument();
  });

  it("sending shows your message at once and asks the gateway", async () => {
    renderScreen(<Chat thread="web" />, []);
    const before = mockBus.all().filter((e) => e.subject === "sense.chat").length;
    await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "coffee 85{Enter}");
    expect(await screen.findByText("coffee 85")).toBeInTheDocument();
    await waitFor(() => expect(mockBus.all().filter((e) => e.subject === "sense.chat")).toHaveLength(before + 1));
    await waitFor(() => expect(JSON.parse(window.localStorage.getItem("mycelium.threads") ?? "[]")[0]?.title).toBe("coffee 85"));
  });

  it("shows a build Main follows as one card: the rounds, the step it is on, the steps to come", () => {
    const since = new Date(Date.now() - 190_000).toISOString();
    const progress = (id: string, seq: number, state: string, title: string, steps: { text: string; state: string; since?: string }[]) =>
      event("out.progress", { ...envelope(id), channel: "web", thread: "web", ref: "b1", seq, state, title, steps, text: title });
    renderScreen(<Chat thread="web" />, [
      progress("p1", 1, "running", "Building water", [{ text: "Round 1 of 6: writing the module", state: "active", since }]),
      progress("p2", 2, "running", "Building water", [
        { text: "Round 1: tests failed: 1 failed, 4 passed", state: "failed" },
        { text: "Round 2 of 6: fixing what failed", state: "active", since },
        { text: "Save it", state: "pending" },
      ]),
    ]);
    const cards = document.querySelectorAll("[data-kind=progress]");
    expect(cards).toHaveLength(1); // one card per build, whatever the number of updates
    const card = screen.getByRole("group", { name: "Building water" });
    expect([...card.querySelectorAll("li")].map((li) => li.getAttribute("data-state"))).toEqual(["failed", "active", "pending"]);
    expect(within(card).getByText(/fixing what failed/)).toHaveTextContent("now: Round 2 of 6: fixing what failed");
    expect(within(card).getByText("3 min")).toBeInTheDocument(); // how long the step it is on has taken
  });

  it("a running card that has heard nothing for a while asks the builder, and ends the way the build did", async () => {
    const quiet = new Date(Date.now() - 20 * 60_000).toISOString(); // its last update, long gone from the bus
    mockBuilds.set("b-quiet", { id: "b-quiet", name: "water", status: "failed", stage: "tests", error: "no working module after 6 rounds", finished: quiet });
    renderScreen(<Chat thread="web" />, [
      event("out.progress", {
        ...envelope("p1"),
        ts: quiet,
        channel: "web",
        thread: "web",
        ref: "b-quiet",
        seq: 3,
        state: "running",
        title: "Building water",
        steps: [
          { text: "Round 6 of 6: building it and running its tests", state: "active", since: quiet },
          { text: "Save it", state: "pending" },
        ],
        text: "Building water",
      }),
    ]);
    const card = screen.getByRole("group", { name: "Building water" });
    expect(await within(card).findByText(/: no working module after 6 rounds$/)).toBeInTheDocument();
    expect(card).toHaveAttribute("data-state", "failed");
    expect([...card.querySelectorAll("li")].map((li) => li.getAttribute("data-state"))).toEqual(["failed", "pending"]);
  });

  it("shows what Main showed from a module under its reply, and a question's blocks above its buttons", () => {
    const stats = { kind: "stats", title: "This week", stats: [{ label: "Total", value: { v: 3420, s: "NT$3,420" } }] };
    renderScreen(<Chat thread="web" />, [
      event("out.say", { ...envelope("a1"), channel: "web", thread: "web", text: "Food was most of it.", blocks: [stats, { kind: "hologram" }] }),
      event("out.ask", { ...envelope("q1"), channel: "web", thread: "web", text: "Delete the taxi?", choices: ["Yes", "No"], ref: "q1", blocks: [stats] }),
    ]);
    const reply = document.querySelector("[data-kind=assistant]")!;
    expect(within(reply as HTMLElement).getByText("NT$3,420")).toBeInTheDocument();
    expect(reply.querySelectorAll("figure")).toHaveLength(1); // a kind the app does not know is left out
    const ask = screen.getByRole("group", { name: "Delete the taxi?" });
    expect(within(ask).getByText("NT$3,420")).toBeInTheDocument();
  });
});
