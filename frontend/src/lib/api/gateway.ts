// What the model gateway says about itself: slots, providers and key states (rpc.llm.config), spend (rpc.llm.usage).

import { rpc } from "./rpc";
import { configReplySchema, usageReplySchema, type ConfigReply, type UsageReply } from "@/lib/schemas";

export function fetchConfig(): Promise<ConfigReply> {
  return rpc("rpc.llm.config", {}, 5, configReplySchema);
}

export function fetchUsage(): Promise<UsageReply> {
  return rpc("rpc.llm.usage", {}, 5, usageReplySchema);
}
