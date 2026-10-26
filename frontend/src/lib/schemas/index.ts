// Runtime shapes for what the backend SENDS. Split by domain, the same seam `lib/api/` and `lib/queries/`
// use, so a shape and the call that parses it are edited together. Types are DERIVED (`z.infer`), never
// written twice. Import `@/lib/schemas`, never a file inside it: the barrel is the public surface.

export * from "./vocabulary";
export * from "./events";
export * from "./system";
export * from "./chat";
export * from "./modules";
export * from "./gateway";
