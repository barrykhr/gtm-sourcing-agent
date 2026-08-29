"use client";

import { ButtonHTMLAttributes, forwardRef } from "react";
import { Loader2 } from "lucide-react";

/** Design-system button (Batch 1) — the one button primitive every
 * redesigned screen should reach for, replacing the ad-hoc
 * `rounded-md bg-accent px-4 py-2 ...` strings copy-pasted across the
 * job workspace. Four variants cover every existing use case: primary
 * (the one loud action per view), secondary (bordered, most actions),
 * ghost (quiet/icon-adjacent), danger (destructive, e.g. revoke/delete). */
const VARIANTS = {
  // Pill-shaped, like every reference site's primary CTA — reserved for
  // the one loud action per view, not every button (a dense candidates
  // table full of pill buttons would fight the "calm" half of "calm
  // intelligence"; secondary/ghost/danger stay rounded-md on purpose).
  primary: "rounded-full bg-accent text-white hover:bg-[var(--accent-hover)] disabled:opacity-50",
  secondary:
    "rounded-md border border-[var(--border)] bg-surface text-foreground hover:bg-[var(--surface-raised)] disabled:opacity-50",
  ghost: "rounded-md text-muted-foreground hover:bg-[var(--border)]/40 hover:text-foreground disabled:opacity-50",
  danger: "rounded-md bg-critical text-white hover:opacity-90 disabled:opacity-50",
} as const;

const SIZES = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
} as const;

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof VARIANTS;
  size?: keyof typeof SIZES;
  busy?: boolean;
  busyLabel?: string;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", busy, busyLabel, disabled, className = "", children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || busy}
      className={`inline-flex shrink-0 items-center justify-center gap-1.5 font-medium ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    >
      {busy && <Loader2 size={size === "sm" ? 13 : 15} className="shrink-0 animate-spin" />}
      {busy ? (busyLabel ?? children) : children}
    </button>
  );
});
