import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Blocks } from "@/components/ui/blocks";
import { PREVIEW_ROWS } from "@/components/ui/blocks/TableBody";
import { blocksSchema } from "@/lib/schemas";

const money = (v: number) => ({ v, s: `NT$${v.toLocaleString("en-US")}` });
const txt = (s: string) => ({ v: s, s });
const col = (key: string, label: string, format: string, prefix = "") => ({ key, label, format, prefix, suffix: "" });
const blocks = (raw: unknown[]) => blocksSchema.parse(raw);

const TABLE = {
  kind: "table",
  title: "Entries",
  columns: [col("what", "What", "text"), col("amount", "Amount", "money", "NT$")],
  rows: [
    [txt("dinner"), money(350)],
    [txt("taxi"), money(520)],
    [txt("latte"), money(85)],
  ],
  total: 3,
};

const cellsOf = (table: HTMLElement, col: number) => within(table).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[col].textContent);

describe("Blocks", () => {
  it("a table sorts by a column's values: the largest first, then the smallest, then as it came", async () => {
    render(<Blocks blocks={blocks([TABLE])} />);
    const table = screen.getByRole("table", { name: "Entries" });
    expect(cellsOf(table, 1)).toEqual(["NT$350", "NT$520", "NT$85"]);
    const amount = within(table).getByRole("button", { name: "Amount" });
    await userEvent.click(amount);
    expect(cellsOf(table, 1)).toEqual(["NT$520", "NT$350", "NT$85"]);
    expect(amount.closest("th")).toHaveAttribute("aria-sort", "descending");
    await userEvent.click(amount);
    expect(cellsOf(table, 1)).toEqual(["NT$85", "NT$350", "NT$520"]);
    await userEvent.click(amount);
    expect(cellsOf(table, 1)).toEqual(["NT$350", "NT$520", "NT$85"]);
    expect(amount.closest("th")).toHaveAttribute("aria-sort", "none");
  });

  it("a long table shows its first rows, the rest on a click, and says when Main kept fewer than there were", async () => {
    const rows = Array.from({ length: 20 }, (_, i) => [txt(`row ${i}`), money(i)]);
    render(<Blocks blocks={blocks([{ ...TABLE, rows, total: 240 }])} />);
    const table = screen.getByRole("table", { name: "Entries" });
    expect(within(table).getAllByRole("row")).toHaveLength(PREVIEW_ROWS + 1);
    await userEvent.click(screen.getByRole("button", { name: "Show all 20" }));
    expect(within(table).getAllByRole("row")).toHaveLength(21);
    expect(screen.getByText("The first 20 of 240")).toBeInTheDocument();
  });

  it("a narrow chat reads each row as a card: its name, its number, the rest", () => {
    render(<Blocks blocks={blocks([TABLE])} />);
    const cards = within(screen.getByRole("list", { name: "Entries" })).getAllByRole("listitem");
    expect(cards[0]).toHaveTextContent("dinnerNT$350");
  });

  it("a bar chart prints every value at its bar, and shows the same points as a table on a click", async () => {
    const chart = {
      kind: "chart",
      chart: "bar",
      title: "By category",
      x: col("category", "Category", "text"),
      series: [col("total", "Total", "money", "NT$")],
      points: [
        { x: txt("food"), y: [money(1820)] },
        { x: txt("coffee"), y: [money(740)] },
      ],
      total: 9,
    };
    render(<Blocks blocks={blocks([chart])} />);
    const bars = screen.getByRole("list", { name: "By category" });
    expect(within(bars).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["foodNT$1,820", "coffeeNT$740"]);
    expect(screen.getByText("The largest 2 of 9")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Legend" })).not.toBeInTheDocument(); // one series: the title names it
    await userEvent.click(screen.getByRole("button", { name: "Table" }));
    const table = screen.getByRole("table", { name: "By category" });
    expect(cellsOf(table, 1)).toEqual(["NT$1,820", "NT$740"]);
    expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "true");
  });

  it("a line chart names itself, has a legend for two series, and reads out the point the keyboard is on", () => {
    const day = (iso: string, s: string) => ({ v: iso, s });
    const chart = {
      kind: "chart",
      chart: "line",
      title: "Water and coffee",
      x: col("day", "Day", "date"),
      series: [col("ml", "Water", "number"), col("cups", "Coffee", "number")],
      points: [
        { x: day("2026-11-01", "Nov 1"), y: [{ v: 1800, s: "1,800" }, { v: 2, s: "2" }] },
        { x: day("2026-11-02", "Nov 2"), y: [{ v: 900, s: "900" }, { v: 3, s: "3" }] },
      ],
      total: 2,
    };
    render(<Blocks blocks={blocks([chart])} />);
    const svg = screen.getByRole("img", { name: "Water and coffee: line chart by Day, Nov 1 to Nov 2" });
    expect(within(screen.getByRole("list", { name: "Legend" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Water", "Coffee"]);
    act(() => svg.focus());
    expect(screen.getByText("Nov 2: Water 900, Coffee 3")).toBeInTheDocument(); // the last point first
    fireEvent.keyDown(svg, { key: "ArrowLeft" });
    expect(screen.getByText("Nov 1: Water 1,800, Coffee 2")).toBeInTheDocument();
    expect(document.querySelector("[data-kind=chart-tip]")).toHaveTextContent("Nov 11,800Water2Coffee");
    fireEvent.keyDown(svg, { key: "Escape" });
    expect(document.querySelector("[data-kind=chart-tip]")).toBeNull();
  });

  it("stats, details and a meter", () => {
    render(
      <Blocks
        blocks={blocks([
          { kind: "stats", title: "This week", stats: [{ label: "Total", value: money(3420) }, { label: "Entries", value: { v: 6, s: "6" } }] },
          { kind: "details", title: "Last expense", items: [{ label: "What", value: txt("dinner") }, { label: "Amount", value: money(350) }] },
          { kind: "meter", label: "Water today", value: { v: 1500, s: "1,500 ml" }, max: { v: 2000, s: "2,000 ml" } },
        ])}
      />,
    );
    const stats = document.querySelector("[data-kind=block-stats]")!;
    expect([...stats.querySelectorAll("dt")].map((d) => `${d.textContent} ${d.nextElementSibling?.textContent}`)).toEqual(["Total NT$3,420", "Entries 6"]);
    expect(document.querySelector("[data-kind=block-details]")).toHaveTextContent("WhatdinnerAmountNT$350");
    const meter = screen.getByRole("meter", { name: "Water today" });
    expect(meter).toHaveAttribute("aria-valuetext", "1,500 ml of 2,000 ml, 75%");
    expect(screen.getByText("1,500 ml / 2,000 ml · 75%")).toBeInTheDocument();
  });

  it("shows nothing without blocks", () => {
    const { container } = render(<Blocks blocks={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
