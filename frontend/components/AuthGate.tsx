"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

/** Blocks rendering the app until we know whether there's a session —
 * AuthProvider already redirects to /login on a 401, this just avoids a
 * flash of real content before that redirect lands. /login and
 * /reset-password are always rendered immediately, since checking auth
 * on either would loop (or bounce someone straight off a reset-link
 * click, before they get to reset anything). */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { status } = useAuth();

  if (pathname === "/login" || pathname === "/reset-password" || status === "authed") return <>{children}</>;
  return <p className="text-sm text-zinc-500">Loading…</p>;
}
