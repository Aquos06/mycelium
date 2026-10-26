"use client";

// Everything under (app) sits behind this: a 401 from any call, or a 4401 from the socket, sends the
// app to /login. There is no session to check up front; the gateway says no when it means no.

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { useBus } from "@/lib/bus";
import { ROUTES } from "@/lib/nav";

export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { onUnauthorized } = useAuth();
  const { status } = useBus();

  useEffect(() => {
    onUnauthorized(() => router.replace(ROUTES.login));
    return () => onUnauthorized(null);
  }, [onUnauthorized, router]);

  useEffect(() => {
    if (status === "unauthorized") router.replace(ROUTES.login);
  }, [status, router]);

  return <>{children}</>;
}
