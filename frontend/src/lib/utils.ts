import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Class names, merged the shadcn way: conditional with clsx, conflicts resolved by tailwind-merge. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
