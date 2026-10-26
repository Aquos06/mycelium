// Every route, in one place, and the tabs the shell draws from them.
//   /                 home            /chat/<thread>       a conversation (default thread "web")
//   /modules          all modules     /modules/<name>      one module or core service
//   /settings/<tab>   models | keys | memory | assistant | system | web
//   /voice            the voice screen (⌘J)    /login     the token

import { Boxes, House, MessageCircle, SlidersHorizontal, type LucideIcon } from "lucide-react";

export const ROUTES = {
  home: "/",
  chat: (thread = "web") => `/chat/${encodeURIComponent(thread)}`,
  modules: "/modules",
  module: (name: string) => `/modules/${encodeURIComponent(name)}`,
  settings: (tab = "models") => `/settings/${tab}`,
  voice: "/voice",
  login: "/login",
} as const;

export const SETTINGS_TABS = ["models", "keys", "memory", "assistant", "system", "web"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];

export interface Tab {
  id: "home" | "chat" | "modules" | "settings";
  label: string;
  href: string;
  icon: LucideIcon;
}

export const TABS: Tab[] = [
  { id: "home", label: "Home", href: ROUTES.home, icon: House },
  { id: "chat", label: "Chat", href: ROUTES.chat(), icon: MessageCircle },
  { id: "modules", label: "Modules", href: ROUTES.modules, icon: Boxes },
  { id: "settings", label: "Settings", href: ROUTES.settings(), icon: SlidersHorizontal },
];

/** Which tab a path belongs to: "/modules/hello" is the modules tab, "/" is home and nothing else is. */
export function tabForPath(pathname: string): Tab["id"] | null {
  if (pathname === "/") return "home";
  const head = pathname.split("/")[1];
  return head === "chat" || head === "modules" || head === "settings" ? head : null;
}

/** The thread a chat path names, or the default. */
export function threadOf(pathname: string): string {
  const parts = pathname.split("/");
  return parts[1] === "chat" && parts[2] ? decodeURIComponent(parts[2]) : "web";
}
