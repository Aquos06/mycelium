"use client";

// Chat text rendered as markdown, in the design system's own type: paragraphs, lists, tables, quotes, inline code
// and code blocks you can copy. GitHub-flavoured (tables, task lists, ~~strike~~), line breaks kept.
//
// What a model writes is not trusted. Raw HTML stays text (react-markdown never renders it), a link keeps only a
// safe scheme and opens in a new tab without a referrer, and an image is shown as a link to it, never loaded:
// text a module or a web page put in front of the model could otherwise make the browser fetch a URL that
// carries what it read.
//
// `streaming` is the reply being written: open marks are closed as they come (lib/markdown) and a caret follows
// the last word.

import { Check, Copy, Image as ImageIcon } from "lucide-react";
import { memo, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components, type Options } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { rehypeCaret, toMarkdown } from "@/lib/markdown";
import { cn } from "@/lib/utils";

const REMARK: Options["remarkPlugins"] = [[remarkGfm, { singleTilde: false }], remarkBreaks]; // 20~25 is a range, not a strike
const STREAM_REHYPE: Options["rehypePlugins"] = [rehypeCaret];

interface TextNode {
  type: string;
  value?: string;
  children?: TextNode[];
  properties?: { className?: unknown };
}

const textOf = (n: TextNode | undefined): string => (n?.type === "text" ? (n.value ?? "") : (n?.children ?? []).map(textOf).join(""));

/** A tag's props with the design system's classes first and react-markdown's hast `node` left out: a DOM element
 *  must not get it. */
function own<P extends { node?: unknown; className?: string }>(base: string, props: P) {
  const { node, ...rest } = props;
  void node;
  return { ...rest, className: cn(base, props.className) };
}

const LINK = "text-moss underline decoration-moss/40 underline-offset-2 hover:decoration-moss";

const COMPONENTS: Components = {
  p: (props) => <p {...own("m-0", props)} />,
  strong: (props) => <strong {...own("font-semibold text-ink", props)} />,
  del: (props) => <del {...own("text-ink3", props)} />,
  a: ({ href, children, ...props }) =>
    href ? (
      <a {...own(LINK, props)} href={href} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    ) : (
      <span>{children}</span> // a scheme we do not follow, or a link still being written
    ),
  img: ({ src, alt }) =>
    typeof src === "string" && src ? (
      <a href={src} target="_blank" rel="noopener noreferrer nofollow" className={cn(LINK, "inline-flex items-center gap-1")}>
        <ImageIcon className="size-3.5 shrink-0" aria-hidden="true" />
        {alt || "image"}
      </a>
    ) : (
      <span>{alt}</span>
    ),
  // a reply sits under the page's own headings: its h1 is a section in it, not the page's title
  h1: (props) => <h3 {...own("m-0 pt-1 text-[18px] leading-snug font-semibold text-ink", props)} />,
  h2: (props) => <h3 {...own("m-0 pt-1 text-[16.5px] leading-snug font-semibold text-ink", props)} />,
  h3: (props) => <h4 {...own("m-0 pt-1 text-[15px] leading-snug font-semibold text-ink", props)} />,
  h4: (props) => <h5 {...own("m-0 text-[15px] font-semibold text-ink", props)} />,
  h5: (props) => <h6 {...own("m-0 text-[14px] font-semibold text-ink2", props)} />,
  h6: (props) => <h6 {...own("m-0 text-[14px] font-semibold text-ink2", props)} />,
  ul: (props) => (
    <ul
      {...own(
        cn("m-0 flex flex-col gap-1", props.className?.includes("contains-task-list") ? "list-none pl-1" : "list-disc pl-5 marker:text-ink3"),
        props,
      )}
    />
  ),
  ol: (props) => <ol {...own("m-0 flex list-decimal flex-col gap-1 pl-5 marker:text-ink3", props)} />,
  li: (props) => <li {...own("pl-0.5 [&>ol]:mt-1 [&>p+p]:mt-2 [&>ul]:mt-1", props)} />,
  input: ({ type, checked }) =>
    type === "checkbox" ? <input type="checkbox" checked={!!checked} disabled readOnly className="mr-1.5 translate-y-px accent-moss" /> : null,
  blockquote: (props) => <blockquote {...own("m-0 flex flex-col gap-2 border-l-2 border-line-strong pl-3 text-ink2", props)} />,
  hr: () => <hr className="my-1 border-0 border-t border-line" />,
  table: (props) => (
    <div className="max-w-full overflow-x-auto rounded-btn border border-line">
      <table {...own("w-full border-collapse text-[13.5px] leading-normal", props)} />
    </div>
  ),
  th: (props) => <th {...own("border-b border-line bg-sunken px-3 py-1.5 text-left font-medium whitespace-nowrap", props)} />,
  td: (props) => <td {...own("border-t border-line px-3 py-1.5 align-top", props)} />,
  code: (props) => <code {...own("rounded-[5px] bg-sunken px-[5px] py-px font-mono text-[0.86em] wrap-break-word text-ink1", props)} />,
  pre: ({ node }) => {
    const code = node?.children.find((c) => c.type === "element" && c.tagName === "code") as TextNode | undefined;
    const cls = code?.properties?.className;
    const lang = (Array.isArray(cls) ? cls : []).map(String).find((c) => c.startsWith("language-"))?.slice(9) ?? null;
    return <CodeBlock lang={lang} text={textOf(code).replace(/\n$/, "")} />;
  },
  span: (props) =>
    "data-caret" in props ? (
      <span data-caret="" className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] animate-pulse-soft bg-moss" aria-hidden="true" />
    ) : (
      <span {...own("", props)} />
    ),
};

function CodeBlock({ lang, text }: { lang: string | null; text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // no clipboard here (plain http, or the browser said no): the text is still there to select
    }
  };
  return (
    <div className="overflow-hidden rounded-btn border border-line bg-sunken" data-kind="code">
      <div className="flex h-8 items-center justify-between border-b border-line pr-1 pl-3 text-[12px] text-ink3">
        <span className="font-mono">{lang ?? "text"}</span>
        <button
          type="button"
          onClick={() => void copy()}
          className="inline-flex h-6 items-center gap-1 rounded-row px-2 hover:bg-hover hover:text-ink"
          aria-label={copied ? "Copied" : "Copy code"}
        >
          {copied ? <Check className="size-3.5 text-moss" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="m-0 overflow-x-auto px-3.5 py-3 font-mono text-[13px] leading-relaxed text-ink1">
        <code>{text}</code>
      </pre>
    </div>
  );
}

/** One message's text. Memoized: a frame of the reply being written re-renders the thread, not every reply. */
export const Markdown = memo(function Markdown({
  text,
  streaming = false,
  className,
}: {
  text: string;
  streaming?: boolean;
  className?: string;
}): ReactNode {
  return (
    <div className={cn("flex min-w-0 flex-col gap-2.5 wrap-break-word", className)} data-markdown="">
      <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={streaming ? STREAM_REHYPE : undefined} components={COMPONENTS}>
        {toMarkdown(text, streaming)}
      </ReactMarkdown>
    </div>
  );
});
