import { notFound } from "next/navigation";
import { SETTINGS_TABS, type SettingsTab } from "@/lib/nav";
import { Settings } from "@/components/screens/Settings";

export default async function SettingsPage({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  if (!(SETTINGS_TABS as readonly string[]).includes(tab)) notFound();
  return <Settings tab={tab as SettingsTab} />;
}
