import { redirect } from "next/navigation";
import { ROUTES } from "@/lib/nav";

/** /chat is the default thread. */
export default function ChatIndexPage() {
  redirect(ROUTES.chat());
}
