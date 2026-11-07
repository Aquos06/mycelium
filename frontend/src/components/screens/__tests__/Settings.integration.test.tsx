import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  process.env.NEXT_PUBLIC_MOCK = "1";
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/settings/builder",
}));

import { Settings } from "@/components/screens/Settings";
import { mockBus, resetMockCoders } from "@/lib/mock";
import { renderScreen } from "./support";

describe("Settings → Builder", () => {
  afterEach(resetMockCoders); // a test that chooses a coder leaves the next one at BUILDER_CODER again

  it("has one top-level heading: the variables below are a section of it", async () => {
    renderScreen(<Settings tab="builder" />, mockBus.all());
    await screen.findByRole("region", { name: "Coders" });
    expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual(["Builder"]);
    expect(screen.getByRole("heading", { level: 2, name: "Set at start" })).toBeInTheDocument();
  });

  it("lists every coder, which can build now and why not, and the default", async () => {
    renderScreen(<Settings tab="builder" />, mockBus.all());
    const coders = await screen.findByRole("region", { name: "Coders" });
    const rows = within(coders).getAllByText(/^(mycelium|opencode|codex|aider|claude_code)$/).map((n) => n.textContent);
    expect(rows).toEqual(["mycelium", "opencode", "codex", "aider", "claude_code"]);
    const ours = coders.querySelector("[data-coder=mycelium]") as HTMLElement;
    expect(within(ours).getByText("default")).toBeInTheDocument();
    expect(within(ours).queryByRole("button", { name: /Use/ })).not.toBeInTheDocument(); // already the default
    const claude = coders.querySelector("[data-coder=claude_code]") as HTMLElement;
    expect(claude).toHaveTextContent("Not ready");
    expect(claude).toHaveTextContent("set ANTHROPIC_API_KEY for the supervisor");
    expect(screen.getByText("BUILDER_AGENTS")).toBeInTheDocument(); // the variables, never their values
  });

  it("choosing a coder makes it the default", async () => {
    renderScreen(<Settings tab="builder" />, mockBus.all());
    await userEvent.click(await screen.findByRole("button", { name: "Use opencode" }));
    const coders = screen.getByRole("region", { name: "Coders" });
    const opencode = coders.querySelector("[data-coder=opencode]") as HTMLElement;
    expect(await within(opencode).findByText("default")).toBeInTheDocument();
    const ours = coders.querySelector("[data-coder=mycelium]") as HTMLElement;
    expect(within(ours).queryByText("default")).not.toBeInTheDocument();
    expect(within(ours).getByRole("button", { name: "Use mycelium" })).toBeEnabled();
  });
});
