// The structure, enforced as a test. Every rule here is one someone would otherwise re-break in six months.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx|css)$/.test(name)) out.push(p);
  }
  return out;
}

const FILES = walk(SRC);
const rel = (p: string) => p.slice(SRC.length + 1);
/** Source with comments stripped, so a law does not trip on its own explanation. */
const code = (p: string) =>
  readFileSync(p, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
const CODE = FILES.filter((p) => !rel(p).includes("__tests__"));
const files = (prefix: string) => CODE.filter((p) => rel(p).startsWith(prefix));

describe("the network", () => {
  it("is touched only in lib/api", () => {
    const offenders = CODE.filter((p) => !rel(p).startsWith("lib/api/") && /\bfetch\(|new WebSocket\(/.test(code(p))).map(rel);
    // lib/bus.tsx owns the one socket; that is its whole job.
    expect(offenders).toEqual(["lib/bus.tsx"]);
  });

  it("components call lib/queries or lib/auth, never lib/api", () => {
    const offenders = files("components/")
      .filter((p) => /from "@\/lib\/api/.test(code(p)))
      .map(rel);
    expect(offenders).toEqual([]);
  });

  it("the barrels are the public surface: no import reaches inside lib/api, lib/queries or lib/schemas", () => {
    const offenders = CODE.filter((p) => {
      const r = rel(p);
      const inside = /from "@\/lib\/(api|queries|schemas)\/[^"]+"/.test(code(p));
      // lib/mock reads the token store straight from client.ts: going through the barrel would import
      // lib/api, whose thunks import lib/mock, a cycle at module load.
      return inside && !r.startsWith("lib/api/") && !r.startsWith("lib/queries/") && !r.startsWith("lib/schemas/") && r !== "lib/mock/index.ts";
    }).map(rel);
    expect(offenders).toEqual([]);
  });
});

describe("the fixtures", () => {
  it("are imported lazily, and only by lib/api thunks and the bus", () => {
    const offenders = CODE.filter((p) => {
      const r = rel(p);
      if (r.startsWith("lib/mock/")) return false;
      const src = code(p);
      const staticImport = /^import [^;]*from "@\/lib\/mock"/m.test(src);
      const lazy = /import\("@\/lib\/mock"\)/.test(src);
      const allowed = r.startsWith("lib/api/") || r === "lib/bus.tsx";
      return staticImport || (lazy && !allowed);
    }).map(rel);
    expect(offenders).toEqual([]);
  });
});

describe("colour", () => {
  it("comes from the tokens: no hex literal in a component", () => {
    const offenders = files("components/")
      .filter((p) => /#[0-9a-fA-F]{3,8}\b/.test(code(p)))
      .map(rel);
    expect(offenders).toEqual([]);
  });

  it("lib/domains.ts carries the same hues as the tokens", () => {
    const css = readFileSync(join(SRC, "app/globals.css"), "utf8");
    const token = (name: string) => new RegExp(`--color-${name}:\\s*(#[0-9a-f]{6})`).exec(css)?.[1];
    const domains = code(join(SRC, "lib/domains.ts"));
    for (const [d, t] of [
      ["sense", "sense"],
      ["brain", "brain"],
      ["mod", "moss"],
      ["build", "build"],
      ["sys", "sys"],
      ["out", "out"],
      ["rpc", "rpc"],
    ]) {
      expect(domains, d).toContain(`${d}: { c: "${token(t)}"`);
    }
  });
});

describe("the screens", () => {
  it("every route renders a screen from components/screens, and every screen has a route", () => {
    const pages = walk(join(SRC, "app")).filter((p) => p.endsWith("page.tsx"));
    const screens = readdirSync(join(SRC, "components/screens")).filter((n) => !n.startsWith("__"));
    const rendered = new Set<string>();
    for (const p of pages) {
      const m = /@\/components\/screens\/(\w+)/.exec(readFileSync(p, "utf8"));
      if (m) rendered.add(m[1]);
    }
    expect([...rendered].sort()).toEqual(screens.sort());
  });

  it("the gateway's API version appears in one place", () => {
    const offenders = CODE.filter((p) => rel(p) !== "lib/api/client.ts" && /["`]\/api\/v1/.test(code(p))).map(rel);
    expect(offenders).toEqual([]);
  });
});
