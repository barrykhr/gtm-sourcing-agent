"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, resetPassword } from "@/lib/api";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, password);
      setDone(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex w-full max-w-sm flex-col gap-6">
      <div className="flex flex-col items-center gap-1.5 text-center">
        <div className="mb-1 flex h-10 w-10 items-center justify-center rounded-full bg-accent text-base font-semibold text-white">
          T
        </div>
        <h1 className="font-display text-2xl italic tracking-tight">Talyn</h1>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-surface p-6 shadow-lg">
        <h2 className="text-base font-semibold tracking-tight">
          {done ? "Password reset" : "Choose a new password"}
        </h2>
        <p className="mt-1 mb-5 text-sm text-zinc-500">
          {done
            ? "You've been logged out everywhere, including this browser — log in with your new password."
            : "This also logs you out everywhere else, in case someone other than you had access."}
        </p>

        {done ? (
          <button
            type="button"
            onClick={() => router.replace("/login")}
            className="w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)]"
          >
            Go to login
          </button>
        ) : !token ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-red-600 dark:text-red-400">
              This reset link is missing its token — it may have been copied incorrectly.
            </p>
            <button
              type="button"
              onClick={() => router.replace("/login")}
              className="self-start text-sm font-medium text-accent hover:underline"
            >
              Back to login
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-zinc-500" htmlFor="new_password">
                New password
              </label>
              <input
                id="new_password"
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-background"
              />
              <p className="text-xs text-zinc-400">At least 8 characters.</p>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-zinc-500" htmlFor="confirm_password">
                Confirm new password
              </label>
              <input
                id="confirm_password"
                type="password"
                required
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-background"
              />
            </div>
            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
                {error}
              </div>
            )}
            <button
              type="submit"
              disabled={busy}
              className="mt-1 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              {busy ? "Working…" : "Reset password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
      <ResetPasswordForm />
    </Suspense>
  );
}
