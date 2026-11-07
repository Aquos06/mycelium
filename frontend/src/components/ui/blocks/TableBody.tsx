"use client";

// Rows a module returned: sortable by any column (numbers by their value, never their text), numbers right-aligned
// in tabular figures. In a narrow chat each row is a card instead: its name, its headline number, the rest below.
// A long table shows its first rows and a button for the rest.

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useState } from "react";
import { isNumeric, nextSort, sortRows, type Sort } from "@/lib/blocks";
import type { BlockColumn, Cell } from "@/lib/schemas";
import { cn } from "@/lib/utils";

export const PREVIEW_ROWS = 8;

export function TableBody({ label, columns, rows }: { label: string; columns: BlockColumn[]; rows: Cell[][] }) {
  const [sort, setSort] = useState<Sort>(null);
  const [all, setAll] = useState(false);
  const sorted = sortRows(rows, sort);
  const shown = all ? sorted : sorted.slice(0, PREVIEW_ROWS);
  const lead = Math.max(0, columns.findIndex((c) => c.format === "text"));
  const headline = columns.findIndex((c, i) => i !== lead && isNumeric(c));

  return (
    <>
      <div className="hidden overflow-x-auto @md:block">
        <table className="w-full border-collapse text-[13.5px] leading-snug" aria-label={label}>
          <thead>
            <tr>
              {columns.map((c, i) => {
                const by = sort?.col === i ? sort.dir : null;
                const Icon = by === "asc" ? ArrowUp : by === "desc" ? ArrowDown : ArrowUpDown;
                return (
                  <th
                    key={c.key + i}
                    scope="col"
                    aria-sort={by === "asc" ? "ascending" : by === "desc" ? "descending" : "none"}
                    className={cn("border-b border-line bg-sunken px-3 py-1.5 font-medium whitespace-nowrap text-ink2", isNumeric(c) ? "text-right" : "text-left")}
                  >
                    <button
                      type="button"
                      onClick={() => setSort(nextSort(sort, i, isNumeric(c)))}
                      className={cn("inline-flex items-center gap-1 rounded-row hover:text-ink", isNumeric(c) && "flex-row-reverse")}
                    >
                      {c.label}
                      <Icon className={cn("size-3", by ? "text-ink" : "text-ink4")} aria-hidden="true" />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, ri) => (
              <tr key={ri} className="border-t border-line first:border-t-0 hover:bg-paper">
                {columns.map((c, i) => (
                  <td key={c.key + i} className={cn("px-3 py-1.5 align-top", isNumeric(c) ? "text-right whitespace-nowrap tabular-nums" : "wrap-break-word", i === lead ? "text-ink" : "text-ink1")}>
                    {r[i]?.s ?? "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="m-0 list-none divide-y divide-line p-0 @md:hidden" aria-label={label}>
        {shown.map((r, ri) => (
          <li key={ri} className="px-4 py-2.5 text-[13.5px]">
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 font-medium wrap-break-word text-ink">{r[lead]?.s}</span>
              {headline >= 0 && <span className="shrink-0 tabular-nums text-ink1">{r[headline]?.s}</span>}
            </div>
            <dl className="m-0 mt-0.5 flex flex-wrap gap-x-3 text-[12.5px] text-ink3">
              {columns.map((c, i) =>
                i === lead || i === headline ? null : (
                  <div key={c.key + i} className="flex gap-1">
                    <dt>{c.label}</dt>
                    <dd className="m-0 text-ink2">{r[i]?.s}</dd>
                  </div>
                ),
              )}
            </dl>
          </li>
        ))}
      </ul>
      {rows.length > PREVIEW_ROWS && (
        <button type="button" onClick={() => setAll(!all)} className="w-full border-t border-sunken px-4 py-2 text-left text-[12.5px] text-ink2 hover:bg-paper hover:text-ink">
          {all ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      )}
    </>
  );
}
