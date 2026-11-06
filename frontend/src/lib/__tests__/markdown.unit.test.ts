import { describe, expect, it } from "vitest";
import { endLists, rehypeCaret, toMarkdown } from "@/lib/markdown";

describe("endLists", () => {
  it("ends a list before the plain sentence after it, as Main's cards are written", () => {
    const card = "A change to expenses (now v0.1.0):\n- `add` takes a category\n- `summary` totals per category\nIt keeps its data.";
    expect(endLists(card)).toBe(
      "A change to expenses (now v0.1.0):\n- `add` takes a category\n- `summary` totals per category\n\nIt keeps its data.",
    );
  });

  it("keeps an indented line in its item, and leaves numbered lists, blank lines and plain text alone", () => {
    expect(endLists("- one\n  more of one\n- two")).toBe("- one\n  more of one\n- two");
    expect(endLists("1. first\n2) second\nafter")).toBe("1. first\n2) second\n\nafter");
    expect(endLists("- one\n\nafter")).toBe("- one\n\nafter");
    expect(endLists("line one\nline two")).toBe("line one\nline two");
  });

  it("does not touch a code fence, even one that looks like a list", () => {
    const fenced = "```\n- not a list\nstill code\n```\nafter";
    expect(endLists(fenced)).toBe(fenced);
    expect(endLists("- item\n```\ncode\n```")).toBe("- item\n\n```\ncode\n```");
  });
});

describe("toMarkdown", () => {
  it("closes the marks a reply being written leaves open, and only then", () => {
    expect(toMarkdown("Spent **85", true)).toBe("Spent **85**");
    expect(toMarkdown("run `mctl", true)).toBe("run `mctl`");
    expect(toMarkdown("Spent **85")).toBe("Spent **85");
  });

  it("leaves dollars alone: no math is rendered", () => {
    expect(toMarkdown("$$ 120 for the bike", true)).toBe("$$ 120 for the bike");
  });
});

describe("rehypeCaret", () => {
  type N = { type: string; tagName?: string; value?: string; properties?: Record<string, unknown>; children?: N[] };
  const el = (tagName: string, ...children: N[]): N => ({ type: "element", tagName, properties: {}, children });
  const text = (value: string): N => ({ type: "text", value });
  const caretIn = (n: N): boolean => !!n.children?.some((c) => c.tagName === "span" && c.properties?.dataCaret);

  it("puts the caret after the last word of the innermost last block", () => {
    const li = el("li", text("two"));
    const tree = el("root", el("p", text("one")), text("\n"), el("ul", el("li", text("one")), text("\n"), li), text("\n"));
    rehypeCaret()(tree);
    expect(caretIn(li)).toBe(true);
  });

  it("never inside a void element", () => {
    const p = el("p", text("a"), el("br"));
    const tree = el("root", p, el("hr"));
    rehypeCaret()(tree);
    expect(caretIn(tree)).toBe(true);
    expect(caretIn(p)).toBe(false);
  });
});
