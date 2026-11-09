import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  process.env.NEXT_PUBLIC_MOCK = "1";
});
const nav = vi.hoisted(() => ({ push: vi.fn(), pathname: "/modules/garden" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => nav.pathname,
}));

// before support: its own next/navigation mock would take over what is imported after it
import { Sidebar } from "@/components/ui/Sidebar";
import { renderScreen } from "@/components/screens/__tests__/support";
import { mockBus, mockRpc, resetMockModules } from "@/lib/mock";

const listed = () => (mockRpc("rpc.sys.list", {}).modules as { name: string }[]).map((m) => m.name);

afterEach(() => {
  resetMockModules();
  nav.push.mockClear();
  nav.pathname = "/modules/garden";
});

/** The trash on a row opens the dialog; its own Delete is the one that deletes. */
async function deleteFromRail(name: string) {
  await userEvent.click(await screen.findByRole("button", { name: `Delete ${name}` }));
  const dialog = await screen.findByRole("alertdialog", { name: `Delete ${name}?` });
  await userEvent.click(within(dialog).getByRole("button", { name: `Delete ${name}` }));
  return dialog;
}

describe("Sidebar", () => {
  it("deletes a grown module from its row through the dialog, and leaves its page", async () => {
    renderScreen(<Sidebar />, mockBus.all());
    await userEvent.click(await screen.findByRole("button", { name: "Delete garden" }));
    expect(await screen.findByRole("alertdialog", { name: "Delete garden?" })).toBeInTheDocument();
    expect(listed()).toContain("garden"); // the trash only opens the dialog
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete garden" }));
    await vi.waitFor(() => expect(nav.push).toHaveBeenCalledWith("/modules")); // its page was open
    expect(listed()).toEqual(["hello", "budget"]);
    await vi.waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("stays where it is when the module deleted is not the one open", async () => {
    nav.pathname = "/chat";
    renderScreen(<Sidebar />, mockBus.all());
    await deleteFromRail("garden");
    await vi.waitFor(() => expect(listed()).not.toContain("garden"));
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("a hand-written module has no delete, and a refusal says why in the dialog", async () => {
    renderScreen(<Sidebar />, mockBus.all());
    expect(await screen.findByRole("link", { name: /hello/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete hello" })).not.toBeInTheDocument();
    const dialog = await deleteFromRail("budget");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("'budget' is being built");
    expect(listed()).toContain("budget");
  });
});
