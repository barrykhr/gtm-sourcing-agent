"use client";

import { CommandPalette } from "@/components/CommandPalette";
import { AccountMenu } from "@/components/AccountMenu";

/** Slim contextual header (Batch 1) — search and account used to live
 * inside the sidebar, taking up vertical space that belongs to
 * navigation, not utilities. Moving them here is what actually makes
 * the sidebar "compact, elegant, secondary" rather than a redesigned
 * version of the same crowded rail. Every page's own title/content
 * starts clean below this, not wrapped in sidebar chrome. */
export function TopBar() {
  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-[var(--border)] px-6">
      <div className="w-full max-w-xs">
        <CommandPalette />
      </div>
      <div className="flex-1" />
      <AccountMenu />
    </header>
  );
}
