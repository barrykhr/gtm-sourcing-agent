"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { AuthGate } from "@/components/AuthGate";

/** Decides the page chrome (Phase 11 design pass): /login gets a bare,
 * centered canvas (no app is logged into yet, nothing to navigate to);
 * every other route gets the full sidebar shell. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (pathname === "/login") {
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
