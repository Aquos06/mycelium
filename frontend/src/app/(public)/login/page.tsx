import type { Metadata } from "next";
import { Login } from "@/components/screens/Login";

export const metadata: Metadata = { title: "mycelium · token", robots: { index: false, follow: false } };

/** Outside (app) on purpose: no socket is opened until there is a token to open it with. */
export default function LoginPage() {
  return <Login />;
}
