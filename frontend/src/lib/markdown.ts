// Chat text as markdown. Main writes for Telegram too, so a reply is mostly plain text with some markdown in it:
// a line break is a line break (remark-breaks), and a sentence right after a list is not part of its last item.
// While a reply is being written, remend closes what the half-written text leaves open (`**bold`, `` `code ``, a
// link without its `)`), so it reads formatted from the first frame instead of flashing raw marks.

import remend from "remend";

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const ITEM = /^ {0,3}([-*+]|\d{1,9}[.)])(\s|$)/;

/** A blank line between a list and an unindented line after it. Markdown would fold that line into the last
 *  item (a lazy continuation), and in chat it never is: Main's cards end their bullets with a plain sentence.
 *  Code fences are left as they are. */
export function endLists(text: string): string {
  const out: string[] = [];
  let fence: string | null = null;
  let inList = false;
  for (const line of text.split("\n")) {
    if (fence) {
      out.push(line);
      if (line.trim().startsWith(fence) && /^[`~]+$/.test(line.trim())) fence = null;
      continue;
    }
    if (ITEM.test(line)) inList = true;
    else if (line.trim() === "") inList = false;
    else if (inList && !/^\s/.test(line)) {
      out.push("");
      inList = false;
    }
    const open = FENCE.exec(line);
    if (open) fence = open[1];
    out.push(line);
  }
  return out.join("\n");
}

/** What to render: the text with its lists ended, and while it is still being written, its open marks closed.
 *  No math is rendered, so `$` and `$$` stay text (a price is not a formula). */
export function toMarkdown(text: string, streaming = false): string {
  const md = endLists(text);
  return streaming ? remend(md, { katex: false, inlineKatex: false }) : md;
}

interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

const VOID = new Set(["br", "hr", "img", "input", "wbr"]);

/** A rehype plugin: the caret of a reply being written, as a `<span data-caret>` after its last word, inside the
 *  innermost last block (a paragraph, a list item, a table cell), so it sits on the line being written instead
 *  of a line of its own under it. */
export function rehypeCaret() {
  return (tree: HastNode) => {
    let at = tree;
    for (;;) {
      const last = (at.children ?? []).findLast((c) => !(c.type === "text" && !c.value?.trim()));
      if (!last || last.type !== "element" || VOID.has(last.tagName ?? "")) break;
      at = last;
    }
    (at.children ??= []).push({ type: "element", tagName: "span", properties: { dataCaret: true }, children: [] });
  };
}
