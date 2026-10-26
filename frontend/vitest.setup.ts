import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount React trees between tests so the DOM (and queries) start clean.
afterEach(() => {
  cleanup();
});
