"use client";

// The bar over a thread: where you are, its title, a new chat, the way to voice.

import { Mic } from "lucide-react";
import { ROUTES } from "@/lib/nav";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Crumb, Right, Sep, Title, Topbar } from "@/components/ui/Topbar";

export function ChatHeader({ title, onNew }: { title: string; onNew: () => void }) {
  return (
    <Topbar className="px-4">
      <Crumb>Chat</Crumb>
      <Sep />
      <Title className="max-w-[360px] truncate">{title}</Title>
      <Right>
        <Button size="sm" onClick={onNew}>
          New chat
        </Button>
        <ButtonLink variant="moss" href={ROUTES.voice}>
          <Mic className="size-3.5" /> Switch to voice
        </ButtonLink>
      </Right>
    </Topbar>
  );
}
