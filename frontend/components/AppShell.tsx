"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { AuthGate } from "@/components/AuthGate";

/** Decides the page chrome (Phase 11 design pass): /login gets a bare,
 * centered canvas (no app is logged into yet, nothing to navigate to);
 * every other route gets the full sidebar shell. /share/[token] (Batch B)
 * is the one route meant for someone outside the recruiting team — a
 * client with a link, not an account — so it gets the same bare canvas
 * and skips AuthGate entirely rather than bouncing them to /login. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (pathname === "/login" || pathname.startsWith("/share/")) {
    return <div className="flex min-h-full items-center justify-center bg-background px-4 py-16">{children}</div>;
  }

  return (
    <div className="flex min-h-full">
      <Sidebar />
      <main className="min-w-0 flex-1 overflow-x-hidden px-8 py-8">
        <div className="mx-auto max-w-6xl">
          <AuthGate>{children}</AuthGate>
        </div>
      </main>
    </div>
  );
}
