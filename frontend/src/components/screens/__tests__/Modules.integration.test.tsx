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

  it("shows what the module has, each of its views, and says which could not be shown and why", async () => {
    renderScreen(<ModuleDetail name="hello" />, mockBus.all());
    const data = await screen.findByRole("region", { name: "Data" });
    expect(await within(data).findByText("412")).toBeInTheDocument(); // Messages: In all
    expect(within(data).getByRole("img", { name: /Last 7 days: line chart by Day/ })).toBeInTheDocument();
    expect(within(data).getByText(/hello\.senders did not answer \(TimeoutError\)/)).toHaveTextContent("By channel: hello.senders");
    expect(within(data).queryByText(/Made from its replies/)).not.toBeInTheDocument(); // hello declares its views
  });

  it("a module that is not running has no one to ask for its data", async () => {
    renderScreen(<ModuleDetail name="garden" />, mockBus.all());
    const data = await screen.findByRole("region", { name: "Data" });
    expect(await within(data).findByText("garden is not running, so there is no one to ask for its data.")).toBeInTheDocument();
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
