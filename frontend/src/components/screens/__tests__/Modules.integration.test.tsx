import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  process.env.NEXT_PUBLIC_MOCK = "1";
});
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/modules",
}));

import { ModuleDetail } from "@/components/screens/ModuleDetail";
import { Modules } from "@/components/screens/Modules";
import { mockBus, mockHalfDelete, mockRpc, resetMockModules } from "@/lib/mock";
import { queryKeys } from "@/lib/queries";
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

  it("deletes a grown module after its dialog says what happens, and goes back to the list", async () => {
    renderScreen(<ModuleDetail name="garden" />, mockBus.all());
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete garden?" });
    expect(dialog).toHaveTextContent("its data is copied aside to a Docker volume first");
    expect(dialog).toHaveTextContent("its code stays in git, under the tag garden-v0.1.0-removed-…");
    expect(push).not.toHaveBeenCalled(); // opening it deletes nothing
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete garden" }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/modules"));
    const listed = mockRpc("rpc.sys.list", {}).modules as { name: string }[];
    expect(listed.map((m) => m.name)).toEqual(["hello", "budget"]); // gone from the list
    resetMockModules();
    push.mockClear();
  });

  it("goes back to the list though the module leaves it before the builder answers", async () => {
    const { client } = renderScreen(<ModuleDetail name="garden" />, mockBus.all());
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete garden?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete garden" }));
    await client.refetchQueries({ queryKey: queryKeys.modules() }); // the supervisor dropped its row first
    expect(screen.queryByRole("heading", { level: 1, name: "garden" })).not.toBeInTheDocument();
    expect(screen.getByRole("alertdialog", { name: "Delete garden?" })).toHaveTextContent("Deleting…"); // still there
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/modules"));
    resetMockModules();
    push.mockClear();
  });

  it("a deletion that stopped halfway is finished from the module's page", async () => {
    mockHalfDelete("garden");
    renderScreen(<ModuleDetail name="garden" />, mockBus.all());
    expect(await screen.findByText(/garden no longer runs, but its folder is still in grown\//)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete garden?" });
    expect(dialog).toHaveTextContent("its code stays in git, under the tag garden-removed-…");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete garden" }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/modules"));
    resetMockModules();
    push.mockClear();
  });

  it("cancel in the dialog keeps the module", async () => {
    renderScreen(<ModuleDetail name="garden" />, mockBus.all());
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect((mockRpc("rpc.sys.list", {}).modules as { name: string }[]).map((m) => m.name)).toContain("garden");
  });

  it("lists health once even when the module declares it, with no two children under one key", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    renderScreen(<ModuleDetail name="budget" />, mockBus.all());
    const actions = await screen.findByRole("combobox", { name: "Action" });
    const names = within(actions).getAllByRole("option").map((o) => o.textContent);
    expect(names.filter((n) => n === "health")).toHaveLength(1);
    expect(error.mock.calls.flat().join(" ")).not.toContain("same key");
    error.mockRestore();
  });

  it("a hand-written module has no Delete", async () => {
    renderScreen(<ModuleDetail name="hello" />, mockBus.all());
    expect(await screen.findByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("a module being built is not deleted, and the dialog says why", async () => {
    renderScreen(<ModuleDetail name="budget" />, mockBus.all());
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete budget?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete budget" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("'budget' is being built");
    expect(push).not.toHaveBeenCalled();
  });

  it("says so when nobody knows the name", async () => {
    renderScreen(<ModuleDetail name="ghost" />, []);
    expect(await screen.findByText("The supervisor knows no module named ghost.")).toBeInTheDocument();
  });
});
