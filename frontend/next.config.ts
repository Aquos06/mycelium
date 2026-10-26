import type { NextConfig } from "next";

// NEXT_PUBLIC_API_BASE is baked into the client bundle at BUILD time (lib/api/client.ts). Unset, a
// production build calls its own origin, which is the deployment this app is for: Caddy in front, /api
// to the gateway, the rest here. Set it only when the gateway is on another origin (the compose dev
// stack: PUBLIC_API_BASE in .env), and then list this origin in the gateway's WEB_CORS_ORIGINS.

const nextConfig: NextConfig = {
  // The Docker image runs `node server.js` from .next/standalone: only the traced files, no node_modules.
  output: "standalone",
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // The voice screen will want the microphone one day; nothing uses it yet, so say so.
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
