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
import { mockBus } from "@/lib/mock";
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

  it("sending shows your message at once and asks the gateway", async () => {
    renderScreen(<Chat thread="web" />, []);
    const before = mockBus.all().filter((e) => e.subject === "sense.chat").length;
    await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "coffee 85{Enter}");
    expect(await screen.findByText("coffee 85")).toBeInTheDocument();
    await waitFor(() => expect(mockBus.all().filter((e) => e.subject === "sense.chat")).toHaveLength(before + 1));
    await waitFor(() => expect(JSON.parse(window.localStorage.getItem("mycelium.threads") ?? "[]")[0]?.title).toBe("coffee 85"));
  });
});
