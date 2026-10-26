import { Chat } from "@/components/screens/Chat";

export default async function ChatPage({ params }: { params: Promise<{ thread: string }> }) {
  const { thread } = await params;
  const id = decodeURIComponent(thread);
  return <Chat key={id} thread={id} />;
}
