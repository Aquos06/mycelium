"use client";

// Numbers over time (or in order), as 2px lines; an area chart washes the space under its line at 10%. One axis,
// from zero, with round ticks in the series' units and hairline grid. A crosshair follows the pointer to the
// nearest point and a readout lists every series there, values first; the keyboard does the same (focus the
// chart, then the arrows, Home and End). The last point of each line is marked, with a surface ring.

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { nearest, niceTicks, num, positions, seriesColor, spread, tickLabel } from "@/lib/blocks";
import type { ChartBlock } from "@/lib/schemas";

const H = 200;
const M = { top: 12, right: 18, bottom: 26, left: 54 };

function useWidth(initial: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(240, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

export function LineChart({ block }: { block: ChartBlock }) {
  const [ref, width] = useWidth(560);
  const [active, setActive] = useState<number | null>(null);
  const { points, series } = block;
  const pos = positions(points.map((p) => p.x));
  const values = points.flatMap((p) => p.y.map(num)).filter((v): v is number => v !== null);
  const ticks = niceTicks(Math.min(...values, 0), Math.max(...values, 0));
  const [lo, hi] = [ticks[0], ticks[ticks.length - 1]];
  const plotW = width - M.left - M.right;
  const X = (t: number) => M.left + t * plotW;
  const Y = (v: number) => M.top + (1 - (v - lo) / (hi - lo || 1)) * (H - M.top - M.bottom);
  const base = Y(Math.max(lo, 0));
  const labels = spread(points.length, Math.max(2, Math.floor(plotW / 84)));
  const last = points.length - 1;

  const line = (si: number) => {
    let d = "";
    let open = false;
    points.forEach((p, i) => {
      const v = num(p.y[si]);
      if (v === null) return void (open = false);
      d += `${open ? "L" : "M"}${X(pos[i]).toFixed(1)},${Y(v).toFixed(1)}`;
      open = true;
    });
    return d;
  };
  const area = (si: number) => {
    const at = points.map((p, i) => [X(pos[i]), num(p.y[si])] as const).filter(([, v]) => v !== null) as [number, number][];
    if (at.length < 2) return "";
    return `M${at[0][0]},${base}${at.map(([x, v]) => `L${x.toFixed(1)},${Y(v).toFixed(1)}`).join("")}L${at[at.length - 1][0]},${base}Z`;
  };

  const point = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setActive(nearest(pos, Math.min(1, Math.max(0, (e.clientX - r.left - M.left) / plotW))));
  };
  const key = (e: KeyboardEvent) => {
    const go = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (go !== undefined) setActive((a) => Math.min(last, Math.max(0, (a ?? last) + go)));
    else if (e.key === "Home") setActive(0);
    else if (e.key === "End") setActive(last);
    else if (e.key === "Escape") setActive(null);
    else return;
    e.preventDefault();
  };

  const name = `${block.title || series.map((s) => s.label).join(", ")}: ${block.chart} chart by ${block.x.label}, ${points[0]?.x.s} to ${points[last]?.x.s}`;
  const at = active === null ? null : points[active];
  const tipLeft = active === null ? 0 : X(pos[active]);

  return (
    <div ref={ref} className="relative px-1 pt-2 pb-1">
      <svg
        width={width}
        height={H}
        className="block max-w-full touch-pan-y outline-none focus-visible:rounded-btn focus-visible:ring-2 focus-visible:ring-moss/40"
        role="img"
        aria-label={name}
        tabIndex={0}
        onPointerMove={point}
        onPointerLeave={() => setActive(null)}
        onFocus={() => setActive((a) => a ?? last)}
        onBlur={() => setActive(null)}
        onKeyDown={key}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={width - M.right} y1={Y(t)} y2={Y(t)} stroke="var(--color-line)" strokeWidth={1} shapeRendering="crispEdges" />
            <text x={M.left - 8} y={Y(t)} dy="0.32em" textAnchor="end" className="fill-ink3 text-[11px] tabular-nums">
              {tickLabel(t, series[0])}
            </text>
          </g>
        ))}
        {labels.map((i) => (
          <text key={i} x={X(pos[i])} y={H - 8} textAnchor={i === 0 && labels.length > 1 ? "start" : i === last && labels.length > 1 ? "end" : "middle"} className="fill-ink3 text-[11px]">
            {points[i].x.s}
          </text>
        ))}
        {block.chart === "area" && series.map((s, si) => <path key={`a${s.key}${si}`} d={area(si)} fill={seriesColor(si, series.length)} fillOpacity={0.1} />)}
        {series.map((s, si) => (
          <path key={`l${s.key}${si}`} d={line(si)} fill="none" stroke={seriesColor(si, series.length)} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {series.map((s, si) => {
          const v = num(points[last]?.y[si]);
          return v === null ? null : <circle key={`e${s.key}${si}`} cx={X(pos[last])} cy={Y(v)} r={4} fill={seriesColor(si, series.length)} stroke="var(--color-surface)" strokeWidth={2} />;
        })}
        {at && (
          <g aria-hidden="true">
            <line x1={tipLeft} x2={tipLeft} y1={M.top} y2={H - M.bottom} stroke="var(--color-ink4)" strokeWidth={1} shapeRendering="crispEdges" />
            {series.map((s, si) => {
              const v = num(at.y[si]);
              return v === null ? null : <circle key={`h${s.key}${si}`} cx={tipLeft} cy={Y(v)} r={4} fill={seriesColor(si, series.length)} stroke="var(--color-surface)" strokeWidth={2} />;
            })}
          </g>
        )}
      </svg>
      <div aria-live="polite" className="sr-only">
        {at ? `${at.x.s}: ${series.map((s, si) => `${s.label} ${at.y[si]?.s ?? "none"}`).join(", ")}` : ""}
      </div>
      {at && (
        <div
          className="pointer-events-none absolute top-2 z-10 min-w-28 rounded-btn border border-line bg-surface px-2.5 py-1.5 text-[12px] shadow-lift"
          style={tipLeft > width / 2 ? { right: width - tipLeft + 10 } : { left: tipLeft + 10 }}
          aria-hidden="true"
          data-kind="chart-tip"
        >
          <div className="text-ink3">{at.x.s}</div>
          {series.map((s, si) => (
            <div key={s.key + si} className="flex items-center gap-2">
              <span className="h-0.5 w-3 rounded-full" style={{ background: seriesColor(si, series.length) }} />
              <span className="font-semibold tabular-nums text-ink">{at.y[si]?.s ?? "—"}</span>
              {series.length > 1 && <span className="text-ink3">{s.label}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
