"use client";

// Saying something, answering a question, voting. Mutations only: what comes back arrives on the bus.

import { useMutation } from "@tanstack/react-query";
import { sendChat, sendFeedback, type FeedbackFields } from "@/lib/api";

export function useSendChat() {
  return useMutation({
    mutationFn: ({ text, thread }: { text: string; thread: string }) => sendChat(text, thread),
  });
}

export function useFeedback() {
  return useMutation({
    mutationFn: ({ ref, thread, ...fields }: { ref: string; thread: string } & FeedbackFields) =>
      sendFeedback(ref, thread, fields),
  });
}
