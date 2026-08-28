"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { logout } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export function AccountMenu() {
  const router = useRouter();
  const { user, refresh } = useAuth();

  if (!user) return <span className="block px-1 text-xs text-zinc-500">recruiter stays the decision-maker</span>;

  async function handleLogout() {
    await logout();
    refresh();
    router.replace("/login");
  }

  return (
    <div className="flex items-center gap-2 rounded-md px-1 py-1">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-white">
        {user.email[0]?.toUpperCase()}
      </div>
      <span className="min-w-0 flex-1 truncate text-xs text-zinc-600 dark:text-zinc-400">{user.email}</span>
      <button
        onClick={handleLogout}
        aria-label="Log out"
        title="Log out"
        className="shrink-0 rounded-md p-1.5 text-zinc-400 hover:bg-background hover:text-zinc-700 dark:hover:text-zinc-200"
      >
        <LogOut size={15} />
      </button>
    </div>
  );
}
