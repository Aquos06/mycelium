import type { Metadata } from "next";
import { BusProvider } from "@/lib/bus";
import { AuthGate } from "@/components/ui/AuthGate";
import { Shell } from "@/components/ui/Shell";

/** Everything in this group is the app: one socket to the bus, the gate that sends a 401 to /login, the
 *  shell with the rail or the tab bar. A personal tool behind a token has nothing for a crawler. */
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <BusProvider>
      <AuthGate>
        <Shell>{children}</Shell>
      </AuthGate>
    </BusProvider>
  );
}
