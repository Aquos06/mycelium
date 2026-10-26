import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  process.env.NEXT_PUBLIC_MOCK = "1";
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/modules",
}));

import { ModuleDetail } from "@/components/screens/ModuleDetail";
import { Modules } from "@/components/screens/Modules";
import { mockBus } from "@/lib/mock";
import { renderScreen } from "./support";

describe("Modules", () => {
  it("lists the grown modules with their state and the core services with a probe", async () => {
    renderScreen(<Modules />, mockBus.all());
    const grown = screen.getByRole("region", { name: "Grown" });
    const hello = await within(grown).findByRole("link", { name: /hello/ });
    expect(hello).toHaveTextContent("Running");
    expect(within(grown).getByRole("link", { name: /budget/ })).toHaveTextContent("Growing");
    expect(within(grown).getByRole("link", { name: /garden/ })).toHaveTextContent("Paused");
    const core = screen.getByRole("region", { name: "Core" });
    expect(await within(core).findByRole("link", { name: /supervisor/ })).toHaveTextContent("Running");
    expect(within(core).getByRole("link", { name: /tracer/ })).toHaveTextContent("No probe");
  });

  it("the filter narrows to one kind", async () => {
    renderScreen(<Modules />, mockBus.all());
    await userEvent.click(screen.getByRole("tab", { name: "Core" }));
    expect(screen.queryByRole("region", { name: "Grown" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Core" })).toBeInTheDocument();
  });
});

describe("ModuleDetail", () => {
  it("shows the module, its wiring, and answers a direct question", async () => {
    renderScreen(<ModuleDetail name="hello" />, mockBus.all());
    expect(await screen.findByRole("heading", { level: 1, name: "hello" })).toBeInTheDocument();
    expect(screen.getByText(/Counts every message/)).toBeInTheDocument();
    expect(screen.getByLabelText("Wiring")).toHaveTextContent("mod.hello.message.counted");
    await userEvent.click(screen.getByRole("button", { name: /Run/ }));
    expect(await screen.findByTestId("ask-result")).toHaveTextContent('"counted": 3');
  });

  it("a core service gets the same page from its description", async () => {
    renderScreen(<ModuleDetail name="memory" />, mockBus.all());
    expect(await screen.findByRole("heading", { level: 1, name: "memory" })).toBeInTheDocument();
    expect(screen.getByText("rpc.memory.lookup")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run/ })).not.toBeInTheDocument();
  });

  it("says so when nobody knows the name", async () => {
    renderScreen(<ModuleDetail name="ghost" />, []);
    expect(await screen.findByText("The supervisor knows no module named ghost.")).toBeInTheDocument();
  });
});
