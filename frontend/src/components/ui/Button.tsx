"use client";

// Every button in the product: a Base UI Button plus a cva variant table, in mycelium's tokens.
//
//   default   a bordered control: Refresh, Logs, New chat
//   primary   the one action in a card: an answer, Run, Open. Ink, never moss: moss is the system's own.
//   ghost     text on nothing: All →, Close
//   moss      the voice affordance, the only moss button. A pill.
//   round     a 32px circle: send, mic

import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import Link from "next/link";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap text-[13px] transition-colors disabled:cursor-default disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "border border-line-strong bg-surface text-ink hover:bg-sidebar",
        primary: "bg-ink font-medium text-white hover:bg-ink1",
        ghost: "text-ink2 hover:bg-sunken hover:text-ink",
        moss: "rounded-[15px] bg-moss-soft pr-3 pl-2.5 font-medium text-moss hover:bg-moss-hover",
        round: "size-8 rounded-full bg-ink4 text-white data-[ready=true]:bg-ink",
        "round-moss": "size-8 rounded-full bg-moss-soft text-moss hover:bg-moss-hover",
      },
      size: {
        md: "h-[30px] rounded-btn px-3",
        sm: "h-7 rounded-[7px] px-2.5 text-[12.5px]",
        none: "",
      },
    },
    compoundVariants: [
      { variant: ["round", "round-moss"], size: ["md", "sm"], className: "h-8 rounded-full px-0" },
    ],
    defaultVariants: { variant: "default", size: "md" },
  },
);

export type ButtonProps = ButtonPrimitive.Props & VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <ButtonPrimitive className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export type ButtonLinkProps = ComponentProps<typeof Link> & VariantProps<typeof buttonVariants>;

export function ButtonLink({ className, variant, size, ...props }: ButtonLinkProps) {
  return <Link className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
