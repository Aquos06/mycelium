"use client";

// This app: the web gateway it talks to, as /system/health describes it.

import { useHealth } from "@/lib/queries";
import { Card } from "@/components/ui/Primitives";
import { Heading, SettingRow } from "./index";
import type { EnvRow } from "./env";

export function WebTab() {
  const { data: health } = useHealth();
  const rows: EnvRow[] = [
    { label: "Gateway", desc: "Where the app sends its requests and opens its socket. Baked into this build; empty means this page's own origin.", env: "NEXT_PUBLIC_API_BASE", value: process.env.NEXT_PUBLIC_API_BASE || "same origin" },
    { label: "Port", desc: "Where the gateway listens; compose publishes it on 127.0.0.1.", env: "WEB_PORT" },
    { label: "Token", desc: "The one login. Empty leaves the gateway open, which is only right on a trusted LAN.", env: "WEB_TOKEN", value: health ? (health.auth ? "required" : "open") : undefined },
    { label: "Your name", desc: "How the home page greets you.", env: "WEB_USER_NAME", value: health?.name },
    { label: "Event buffer", desc: "Bus events the gateway keeps for a page that just opened.", env: "WEB_EVENT_BUFFER", value: health ? `${health.events} held now` : undefined },
    { label: "RPC timeout", desc: "Seconds a request through /rpc waits by default.", env: "WEB_RPC_TIMEOUT" },
    { label: "Allowed origins", desc: "Where the gateway lets a browser call from. This app's origin must be in it.", env: "WEB_CORS_ORIGINS" },
    { label: "Clients", desc: "Pages connected to the socket right now.", env: "—", value: health ? String(health.clients) : undefined },
    { label: "Version", desc: "The SDK version the gateway runs.", env: "—", value: health?.version },
  ];
  return (
    <>
      <Heading title="This app" lead="The web gateway (services/web) that this page talks to: the bus over one websocket, your messages in on channel web." />
      <Card>
        {rows.map((r) => (
          <SettingRow key={r.env + r.label} r={r} />
        ))}
      </Card>
    </>
  );
}
