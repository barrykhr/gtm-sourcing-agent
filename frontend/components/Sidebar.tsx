"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Briefcase, BookOpen, Users, UsersRound } from "lucide-react";
import { CommandPalette } from "@/components/CommandPalette";
import { AccountMenu } from "@/components/AccountMenu";

const LINKS = [
  { href: "/", label: "Jobs", icon: Briefcase },
  { href: "/candidates", label: "Candidates", icon: Users },
  { href: "/team", label: "Team", icon: UsersRound },
  { href: "/guide", label: "Guide", icon: BookOpen },
] as const;

/** Persistent left sidebar (Phase 11 design pass) — the primary
 * navigation pattern of Linear/Vercel/Retool/Notion, replacing the
 * top-bar-only nav this product had before. Account + search live here
 * too, so the top of each page is free for the page's own content. */
export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-[var(--border)] bg-surface">
      <div className="px-4 pb-3 pt-5">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          Talyn
        </Link>
      </div>

      <div className="px-3 pb-3">
        <CommandPalette />
      </div>

      <nav className="flex-1 space-y-0.5 px-3">
        {LINKS.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium ${
                active
                  ? "bg-accent/10 text-accent"
                  : "text-zinc-500 hover:bg-background hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              }`}
            >
              <Icon size={16} className="shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-[var(--border)] p-3">
        <AccountMenu />
      </div>
    </aside>
  );
}
