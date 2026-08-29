"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Briefcase, BookOpen, Users, UsersRound } from "lucide-react";

const LINKS = [
  { href: "/", label: "Jobs", icon: Briefcase },
  { href: "/candidates", label: "Candidates", icon: Users },
  { href: "/team", label: "Team", icon: UsersRound },
  { href: "/guide", label: "Guide", icon: BookOpen },
] as const;

/** Navigation infrastructure, not the product (Batch 1 redesign) —
 * compact, quiet, blends into the page background rather than reading
 * as its own panel. Search and account moved to TopBar so this rail is
 * nothing but "where am I, where can I go" — the workspace canvas next
 * to it is where the actual product lives. */
export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-[var(--border)] px-3 py-5">
      <Link href="/" className="font-display mb-6 px-2 text-lg italic tracking-tight">
        Talyn
      </Link>

      <nav className="flex flex-1 flex-col gap-0.5">
        {LINKS.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm ${
                active
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-muted-foreground hover:bg-[var(--border)]/40 hover:text-foreground"
              }`}
            >
              <Icon size={16} className="shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
