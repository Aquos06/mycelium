"use client";

// Ask twice: the first click arms an action, a second within four seconds does it. Pause and the deploys on a
// module's page go through it, so nothing that stops or rebuilds a module is one click. Deleting one asks more: a
// dialog that says what happens to it (components/ui/DeleteModuleDialog).

import { useState } from "react";

export const CONFIRM_MS = 4000;

export function useConfirm<A extends string>(): { armed: A | null; confirm: (action: A, run: () => void) => void } {
  const [armed, setArmed] = useState<A | null>(null);
  const confirm = (action: A, run: () => void) => {
    if (armed !== action) {
      setArmed(action);
      window.setTimeout(() => setArmed((x) => (x === action ? null : x)), CONFIRM_MS);
      return;
    }
    setArmed(null);
    run();
  };
  return { armed, confirm };
}
