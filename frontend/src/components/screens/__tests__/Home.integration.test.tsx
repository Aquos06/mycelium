import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  process.env.NEXT_PUBLIC_MOCK = "1";
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/",
}));

import { Home } from "@/components/screens/Home";
import { mockBus } from "@/lib/mock";
import { renderScreen } from "./support";

describe("Home", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("greets by name, reads the bus, and shows what needs you", async () => {
    renderScreen(<Home />, mockBus.all());

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(/Good \w+, Hansen/);
    const needs = screen.getByRole("region", { name: "Needs you" });
    expect(within(needs).getByText("Should I keep the Friday reminder for the garden watering?")).toBeInTheDocument();
    expect(within(needs).getByText(/Yesterday's notes are consolidated/)).toBeInTheDocument();

    const timeline = screen.getByRole("list", { name: "Timeline" });
    expect(within(timeline).getByText("You said “dinner with Mei at 7, remind me at 6” on telegram")).toBeInTheDocument();
    expect(within(timeline).getByText("Planned a reply and remembered it")).toBeInTheDocument();
    expect(within(timeline).queryByText(/trace\.plan/)).not.toBeInTheDocument(); // the machine's side only in raw mode

    // the alive tile and the senses come from the same events
    expect(await screen.findByText("hello")).toBeInTheDocument();
    expect(screen.getByTitle("telegram")).toHaveTextContent("Chat");
  });

  it("raw mode shows subjects instead of sentences", async () => {
    renderScreen(<Home />, mockBus.all());
    await screen.findByRole("list", { name: "Timeline" });
    await userEvent.click(screen.getByRole("button", { name: "raw bus" }));
    expect(screen.getAllByText("sense.chat").length).toBeGreaterThan(0);
  });

  it("answering a question publishes sense.feedback with the ask's ref", async () => {
    const before = mockBus.all().filter((e) => e.subject === "sense.feedback").length;
    renderScreen(<Home />, mockBus.all());
    const needs = await screen.findByRole("region", { name: "Needs you" });
    await userEvent.click(within(needs).getByRole("button", { name: "Keep it" }));
    await waitFor(() => {
      const fb = mockBus.all().filter((e) => e.subject === "sense.feedback");
      expect(fb).toHaveLength(before + 1);
      expect(fb.at(-1)!.data.answer).toBe("Keep it");
      expect(fb.at(-1)!.data.ref).toBe(mockBus.all().find((e) => e.subject === "out.ask")!.data.ref);
    });
  });

  it("a missing key for an active provider is a card; a missing one for a shadow is not", async () => {
    renderScreen(<Home />, mockBus.all());
    await screen.findByRole("region", { name: "Needs you" });
    // the fixture's planner slot is active on claude (key ok); openai (key missing) is neither active nor shadow
    await waitFor(() => expect(screen.queryByText(/OPENAI_API_KEY is not set/)).not.toBeInTheDocument());
  });
});
