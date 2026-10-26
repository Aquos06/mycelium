"use client";

// The one login: a token the gateway compares against WEB_TOKEN. No accounts, no sessions to refresh.
// `AuthGate` (components/ui) sends the app to /login whenever a call or the socket answers 401.

import { useCallback } from "react";
import { ApiError, fetchHealth, getToken, setToken, setUnauthorizedHandler } from "@/lib/api";

export interface LoginResult {
  ok: boolean;
  error?: string;
  name?: string;
}

export function useAuth() {
  /** Store the token, then prove it against /system/health. A wrong one is reported, not kept. */
  const login = useCallback(async (token: string): Promise<LoginResult> => {
    setToken(token.trim() || null);
    try {
      const h = await fetchHealth();
      return { ok: true, name: h.name };
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setToken(null);
        return { ok: false, error: "That is not the gateway's token." };
      }
      return { ok: false, error: e instanceof Error ? e.message : "The gateway did not answer." };
    }
  }, []);

  const logout = useCallback(() => setToken(null), []);

  return { login, logout, token: getToken(), onUnauthorized: setUnauthorizedHandler };
}
