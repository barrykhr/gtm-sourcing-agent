"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { AuthGate } from "@/components/AuthGate";

/** Decides the page chrome (Batch 1 redesign): /login gets a bare,
 * centered canvas (no app is logged into yet, nothing to navigate to);
 * every other route gets the sidebar + contextual TopBar shell, with
 * the workspace canvas (the actual product) filling the rest of the
 * screen underneath. /share/[token] (Batch B) is the one route meant
 * for someone outside the recruiting team — a client with a link, not
 * an account — so it gets the same bare canvas and skips AuthGate
 * entirely rather than bouncing them to /login. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (pathname === "/login" || pathname.startsWith("/share/")) {
    // A stronger version of the body's wash — the one moment in the app
    // that's allowed to look like a landing-page hero rather than a
    // workspace, since there's no data-dense content underneath it to
    // fight with.
    return (
      <div
        className="flex min-h-full items-center justify-center px-4 py-16"
        style={{
          backgroundColor: "var(--background)",
          backgroundImage:
            "radial-gradient(ellipse 1100px 750px at 12% -8%, color-mix(in srgb, var(--wash) 70%, transparent), transparent 60%), " +
            "radial-gradient(ellipse 900px 700px at 95% 105%, color-mix(in srgb, var(--accent) 22%, transparent), transparent 55%)",
        }}
      >
        {children}
      </div>
    );
  }

  return (
    <div className="flex min-h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-w-0 flex-1 overflow-x-hidden px-8 py-8">
          <div className="mx-auto max-w-6xl">
            <AuthGate>{children}</AuthGate>
          </div>
        </main>
      </div>
    </div>
  );
}
