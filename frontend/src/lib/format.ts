// Small formatters shared by the screens. Pure: every one takes its clock, so a test can pin it.

export function hhmm(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toTimeString().slice(0, 5);
}

/** How long ago, for a row that is fresh: "now", "2m", "3h"; older rows show the clock time. */
export function ago(iso: string, now = Date.now()): string {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 45) return "now";
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 6 * 3600) return `${Math.round(s / 3600)}h`;
  return hhmm(iso);
}

/** The timeline's group label for a timestamp: Just now, This morning, This afternoon, This evening, Yesterday, Earlier. */
export function groupOf(iso: string, now = new Date()): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "Earlier";
  const diff = now.getTime() - d.getTime();
  if (diff < 10 * 60_000) return "Just now";
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    const h = d.getHours();
    return h < 12 ? "This morning" : h < 18 ? "This afternoon" : "This evening";
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  return d.toDateString() === yesterday.toDateString() ? "Yesterday" : "Earlier";
}

export function dayPart(now = new Date()): string {
  const h = now.getHours();
  return h < 5 ? "night" : h < 12 ? "morning" : h < 18 ? "afternoon" : "evening";
}

export function greeting(name: string, now = new Date()): string {
  return `Good ${dayPart(now)}, ${name}`;
}

export function usd(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined ? "—" : `$${v.toFixed(digits)}`;
}

export function compact(n: number): string {
  return n >= 10_000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export function plural(n: number, one: string, many = one + "s"): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Seven bars of activity: counts per bucket over the last `hours` hours, scaled 0..100 (0 stays 0). */
export function sparkline(timestamps: string[], hours = 7, now = Date.now()): number[] {
  const buckets = new Array<number>(hours).fill(0);
  const span = 3600_000;
  for (const iso of timestamps) {
    const t = new Date(iso).getTime();
    if (isNaN(t)) continue;
    const i = hours - 1 - Math.floor((now - t) / span);
    if (i >= 0 && i < hours) buckets[i] += 1;
  }
  const max = Math.max(1, ...buckets);
  return buckets.map((b) => (b === 0 ? 0 : Math.max(12, Math.round((b / max) * 100))));
}

export function initials(name: string): string {
  return (name.trim()[0] ?? "?").toUpperCase();
}
