"use client";

/**
 * Shared auth state (Phase 7) — one `GET /auth/me` per navigation,
 * consumed by both AuthGate (redirect-if-anonymous) and AccountMenu
 * (show who's logged in / log out), instead of each fetching
 * independently and racing each other.
 */

import { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, AuthUser, getMe } from "@/lib/api";

type AuthStatus = "checking" | "authed" | "anon";

type AuthState = {
  user: AuthUser | null;
  status: AuthStatus;
  refresh: () => void;
};

const AuthContext = createContext<AuthState>({ user: null, status: "checking", refresh: () => {} });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("checking");

  function refresh() {
    getMe()
      .then((u) => {
        setUser(u);
        setStatus("authed");
      })
      .catch((e) => {
        setUser(null);
        setStatus("anon");
        // /share/[token] is the one route meant for a logged-out visitor
        // (see AppShell's routing comment) — must match that exemption
        // exactly, or an anonymous client following a share link gets
        // bounced to /login instead of seeing the public status page.
        const isPublicRoute = pathname === "/login" || pathname.startsWith("/share/");
        if (!isPublicRoute && e instanceof ApiError && e.status === 401) {
          router.replace("/login");
        }
      });
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, [pathname]);

  return <AuthContext.Provider value={{ user, status, refresh }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
