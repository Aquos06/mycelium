import { ModuleDetail } from "@/components/screens/ModuleDetail";

export default async function ModulePage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  return <ModuleDetail name={decodeURIComponent(name)} />;
}
