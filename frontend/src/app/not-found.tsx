import Link from "next/link";
import { ROUTES } from "@/lib/nav";

export default function NotFound() {
  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-3 bg-paper p-6 text-center">
      <span className="font-mono text-[13px] text-ink3">404</span>
      <h1 className="m-0 text-[22px] font-semibold tracking-[-0.02em]">Nothing grows here.</h1>
      <Link href={ROUTES.home} className="text-[13.5px]">
        Back home
      </Link>
    </div>
  );
}
