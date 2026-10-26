// Client for the web gateway (services/web): the ONLY place that touches the network.
//
// Split by DOMAIN, matching the gateway's own `<domain>/router.py` seam. The app imports `@/lib/api`
// and nowhere deeper: this barrel is the public surface. Components do not import it either; they call
// the hooks in `@/lib/queries`.

export * from "./client";
export * from "./system";
export * from "./events";
export * from "./chat";
export * from "./rpc";
export * from "./modules";
export * from "./gateway";
