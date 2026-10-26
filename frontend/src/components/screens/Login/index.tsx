"use client";

// The token. The gateway asks for one when WEB_TOKEN is set; it stays in this browser.

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth";
import { ROUTES } from "@/lib/nav";
import { Button } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Logo";
import { ErrorLine } from "@/components/ui/Primitives";

export function Login() {
  const router = useRouter();
  const { login } = useAuth();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!value.trim() || busy) return;
    setBusy(true);
    setError(null);
    const r = await login(value);
    setBusy(false);
    if (r.ok) router.replace(ROUTES.home);
    else setError(r.error ?? "That did not work.");
  };

  return (
    <div className="flex h-dvh items-center justify-center bg-paper p-6">
      <form className="flex w-full max-w-[380px] flex-col gap-3.5 rounded-card border border-line bg-surface p-6" onSubmit={submit} aria-label="Token">
        <div className="flex items-center gap-2">
          <div className="flex size-7">
            <Logo />
          </div>
          <span className="text-[14px] font-semibold tracking-[-0.01em]">mycelium</span>
        </div>
        <span className="text-[13.5px] text-pretty text-ink2">
          This gateway asks for its token (WEB_TOKEN in the stack&apos;s .env). It stays in this browser.
        </span>
        <input
          type="password"
          autoComplete="off"
          placeholder="token"
          aria-label="Token"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoFocus
          className="h-9 rounded-btn border border-line-strong px-3 font-mono text-[13px] outline-none focus:border-ink3"
        />
        {error && <ErrorLine>{error}</ErrorLine>}
        <Button type="submit" variant="primary" disabled={!value.trim() || busy}>
          Open
        </Button>
      </form>
    </div>
  );
}
