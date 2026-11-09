"use client";

// The left rail (md and up): where you are, what is grown, the recent conversations, settings, you. A module the
// builder grew can be deleted from its row: the trash shows on hover (always on a touch screen) and opens the dialog
// that says what happens to it.

import { Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useBus } from "@/lib/bus";
import { byRecent, THREADS_KEY, type Thread } from "@/lib/chat";
import { initials } from "@/lib/format";
import { useStored } from "@/lib/hooks";
import { ROUTES, TABS, tabForPath, threadOf } from "@/lib/nav";
import { deletable, useMissingKeys, useModules } from "@/lib/queries";
import type { ModuleRow } from "@/lib/schemas";
import { statusOf } from "@/lib/status";
import { cn } from "@/lib/utils";
import { DeleteModuleDialog, type DeleteTarget } from "./DeleteModuleDialog";
import { Logo } from "./Logo";
import { StatusDot } from "./Primitives";

const SENSES = ["sense.chat", "sense.voice", "sense.screen", "sense.cam", "sense.iot"];
const NO_THREADS: Thread[] = [];

/** The recent conversations, newest first; re-reads when the chat touches one (lib/storage notifies). */
export function useThreads(): Thread[] {
  const [list] = useStored<Thread[]>(THREADS_KEY, NO_THREADS);
  return useMemo(() => list.slice().sort(byRecent), [list]);
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);
  const tab = tabForPath(pathname);
  const thread = threadOf(pathname);
  const { events, status, name } = useBus();
  const mods = useModules();
  const { modules } = mods;
  const missing = useMissingKeys();
  const threads = useThreads();

  const alive = modules.filter((m) => statusOf(m) === "running").length;
  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const e of events) {
      if (!e.subject.startsWith("mod.")) continue;
      const n = e.subject.split(".")[1];
      out[n] = (out[n] ?? 0) + 1;
    }
    return out;
  }, [events]);
  const sensesOn = useMemo(() => SENSES.filter((s) => events.some((e) => e.subject === s)).length, [events]);

  const live =
    status === "live"
      ? { text: "Live", cls: "text-moss" }
      : status === "connecting"
        ? { text: "Connecting", cls: "text-amber" }
        : status === "offline"
          ? { text: "Offline", cls: "text-ink3" }
          : status === "refused"
            ? { text: "Refused", cls: "text-amber" }
            : { text: "Locked", cls: "text-ink3" };

  return (
    <aside className="hidden w-[236px] shrink-0 flex-col overflow-y-auto border-r border-line bg-sidebar px-2 py-3 md:flex">
      <div className="flex items-center gap-2 px-2 pt-1 pb-3.5">
        <div className="flex size-[22px]">
          <Logo draw />
        </div>
        <span className="text-[14px] font-semibold tracking-[-0.01em]">mycelium</span>
        <span className={cn("ml-auto flex items-center gap-[5px] text-[11.5px] font-medium", live.cls)} data-status={status}>
          <span className={cn("size-1.5 shrink-0 rounded-full bg-current", status === "live" && "animate-pulse-soft")} />
          {live.text}
        </span>
      </div>

      <nav className="flex flex-col gap-px" aria-label="Main">
        {TABS.filter((t) => t.id !== "settings").map((t) => {
          const Icon = t.icon;
          const href = t.id === "chat" ? ROUTES.chat(thread) : t.href;
          return (
            <NavItem key={t.id} href={href} on={tab === t.id} icon={<Icon className="size-[15px]" strokeWidth={1.9} />} label={t.label}>
              {t.id === "modules" && modules.length > 0 && <span className="ml-auto text-[11.5px] text-ink3">{alive}</span>}
            </NavItem>
          );
        })}
      </nav>

      <Section label="Grown">
        {modules.length === 0 && <div className="px-2.5 py-1 text-[12.5px] text-ink3">No modules yet</div>}
        {modules.map((m) => (
          <GrownRow
            key={m.name}
            m={m}
            on={pathname === ROUTES.module(m.name)}
            count={counts[m.name] ?? m.version}
            onDelete={
              deletable(m.name, mods) ? () => setDeleting({ name: m.name, version: m.version, grown: mods.grown.includes(m.name) }) : undefined
            }
          />
        ))}
      </Section>

      <Section label="Recent chats">
        {threads.length === 0 && <div className="px-2.5 py-1 text-[12.5px] text-ink3">Nothing yet</div>}
        {threads.slice(0, 6).map((t) => (
          <SideRow key={t.id} href={ROUTES.chat(t.id)} on={tab === "chat" && thread === t.id} title={t.title}>
            <span className="truncate text-ink2">{t.title || t.id}</span>
          </SideRow>
        ))}
      </Section>

      <div className="mt-auto">
        <NavItem href={ROUTES.settings()} on={tab === "settings"} icon={<SettingsIcon />} label="Settings">
          {missing.length > 0 && <span className="ml-auto size-1.5 rounded-full bg-amber" title={`${missing.join(", ")} not set`} />}
        </NavItem>
        <div className="mt-1.5 flex items-center gap-[9px] border-t border-line px-1.5 pt-2.5 pb-0.5">
          <div className="flex size-[26px] items-center justify-center rounded-full bg-active text-[12px] font-semibold text-ink2">
            {initials(name || "?")}
          </div>
          <div className="flex min-w-0 flex-col leading-tight">
            <span className="truncate text-[13px] font-medium">{name || "…"}</span>
            <span className="text-[11.5px] text-ink3">
              {sensesOn} {sensesOn === 1 ? "sense" : "senses"} on
            </span>
          </div>
        </div>
      </div>
      <DeleteModuleDialog
        target={deleting}
        onClose={() => setDeleting(null)}
        onDeleted={(gone) => pathname === ROUTES.module(gone) && router.push(ROUTES.modules)}
      />
    </aside>
  );
}

function SettingsIcon() {
  const Icon = TABS[3].icon;
  return <Icon className="size-[15px]" strokeWidth={1.9} />;
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="px-2.5 pt-5 pb-1.5 text-[12px] font-medium text-ink3">{label}</div>
      <div className="flex flex-col gap-px">{children}</div>
    </div>
  );
}

function NavItem({ href, on, icon, label, children }: { href: string; on: boolean; icon: React.ReactNode; label: string; children?: React.ReactNode }) {
  return (
    <Link
      href={href}
      aria-current={on ? "page" : undefined}
      className={cn(
        "flex h-[30px] w-full items-center gap-[9px] rounded-row px-2.5 text-ink2 no-underline hover:bg-hover hover:text-ink2",
        on && "bg-active font-medium text-ink hover:text-ink",
      )}
    >
      {icon}
      <span>{label}</span>
      {children}
    </Link>
  );
}

function SideRow({
  href,
  on,
  title,
  className,
  children,
}: {
  href: string;
  on: boolean;
  title?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      title={title}
      aria-current={on ? "page" : undefined}
      className={cn("flex h-[30px] w-full items-center gap-[9px] rounded-row px-2.5 text-ink1 no-underline hover:bg-hover", on && "bg-active", className)}
    >
      {children}
    </Link>
  );
}

/** A module's row: its link, and for one the builder grew a delete button beside it (not inside: a button in a
 *  link is not allowed), which opens the dialog. */
function GrownRow({ m, on, count, onDelete }: { m: ModuleRow; on: boolean; count: string | number; onDelete?: () => void }) {
  return (
    <div className="group relative">
      <SideRow href={ROUTES.module(m.name)} on={on} title={m.manifest.purpose} className={onDelete ? "group-hover:bg-hover" : undefined}>
        <StatusDot kind={statusOf(m)} />
        <span className="min-w-0 truncate font-mono text-[13px]">{m.name}</span>
        <span
          className={cn(
            "ml-auto text-[11.5px] text-ink3",
            onDelete && "group-focus-within:invisible group-hover:invisible pointer-coarse:invisible",
          )}
        >
          {count}
        </span>
      </SideRow>
      {onDelete && (
        <button
          type="button"
          aria-label={`Delete ${m.name}`}
          title={`Delete ${m.name}…`}
          aria-haspopup="dialog"
          onClick={onDelete}
          className="absolute top-[3px] right-1 flex size-6 items-center justify-center rounded-[6px] text-ink3 opacity-0 group-hover:opacity-100 hover:bg-active hover:text-red-text focus-visible:opacity-100 pointer-coarse:opacity-100"
        >
          <Trash2 className="size-[13px]" strokeWidth={1.9} />
        </button>
      )}
    </div>
  );
}
