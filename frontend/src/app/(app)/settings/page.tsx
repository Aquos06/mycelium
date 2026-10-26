import { redirect } from "next/navigation";
import { ROUTES } from "@/lib/nav";

/** /settings opens on the models tab. */
export default function SettingsIndexPage() {
  redirect(ROUTES.settings());
}
