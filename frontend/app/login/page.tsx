"use client";

import Script from "next/script";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, forgotPassword, getAuthStatus, googleLogin, login, signup } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }) => void;
          renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [mode, setMode] = useState<"login" | "signup" | "forgot">("login");
  const [forgotSent, setForgotSent] = useState(false);
  const [signupRequiresCode, setSignupRequiresCode] = useState(false);
  const [googleClientId, setGoogleClientId] = useState<string | null>(null);
  const [googleScriptLoaded, setGoogleScriptLoaded] = useState(false);
  const googleButtonRef = useRef<HTMLDivElement>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [signupCode, setSignupCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getAuthStatus()
      .then((s) => {
        setSignupRequiresCode(s.signup_requires_code);
        setGoogleClientId(s.google_client_id);
      })
      .catch(() => {});
  }, []);

  // Google Identity Services calls this directly with the signed
  // credential — it never goes through handleSubmit's email/password path.
  async function handleGoogleCredential(response: { credential: string }) {
    setBusy(true);
    setError(null);
    try {
      await googleLogin(response.credential);
      refresh();
      router.replace("/");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Google sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!googleScriptLoaded || !googleClientId || !googleButtonRef.current || !window.google) return;
    window.google.accounts.id.initialize({ client_id: googleClientId, callback: handleGoogleCredential });
    window.google.accounts.id.renderButton(googleButtonRef.current, {
      theme: "outline",
      size: "large",
      width: 320,
      text: "continue_with",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [googleScriptLoaded, googleClientId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "forgot") {
        await forgotPassword(email);
        setForgotSent(true);
        return;
      }
      if (mode === "signup") {
        await signup(email, password, signupCode || undefined);
      } else {
        await login(email, password);
      }
      refresh();
      router.replace("/");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  function switchMode(m: "login" | "signup" | "forgot") {
    setMode(m);
    setError(null);
    setForgotSent(false);
  }

  return (
    <div className="flex w-full max-w-sm flex-col gap-6">
      {googleClientId && (
        <Script
          src="https://accounts.google.com/gsi/client"
          strategy="afterInteractive"
          onLoad={() => setGoogleScriptLoaded(true)}
        />
      )}
      <div className="flex flex-col items-center gap-1.5 text-center">
        <div className="mb-1 flex h-10 w-10 items-center justify-center rounded-full bg-accent text-base font-semibold text-white">
          T
        </div>
        <h1 className="font-display text-2xl italic tracking-tight">Talyn</h1>
        <p className="text-sm text-muted-foreground">Recruiter stays the decision-maker.</p>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-surface p-6 shadow-lg">
        {mode !== "forgot" && googleClientId && (
          <>
            <div ref={googleButtonRef} className="mb-4 flex justify-center" />
            <div className="mb-4 flex items-center gap-3">
              <div className="h-px flex-1 bg-zinc-200 dark:bg-zinc-800" />
              <span className="text-xs text-zinc-400">or</span>
              <div className="h-px flex-1 bg-zinc-200 dark:bg-zinc-800" />
            </div>
          </>
        )}
        {mode !== "forgot" && (
          <div className="mb-5 flex gap-1 rounded-md border border-zinc-200 p-1 dark:border-zinc-800">
            {(["login", "signup"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => switchMode(m)}
                className={`flex-1 rounded px-3 py-1.5 text-sm font-medium ${
                  mode === m
                    ? "bg-accent text-white"
                    : "text-zinc-500 hover:bg-background dark:hover:bg-zinc-800"
                }`}
              >
                {m === "login" ? "Log in" : "Create account"}
              </button>
            ))}
          </div>
        )}

        <h2 className="text-base font-semibold tracking-tight">
          {mode === "forgot" ? "Reset your password" : mode === "signup" ? "Create your account" : "Welcome back"}
        </h2>
        <p className="mt-1 mb-5 text-sm text-zinc-500">
          {mode === "forgot"
            ? "Enter your email and we'll send you a link to choose a new password."
            : mode === "signup"
              ? "A shared recruiting workspace — every account sees the same jobs and candidates."
              : "Log in to your recruiting workspace."}
        </p>

        {mode === "forgot" && forgotSent ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              If an account exists for <span className="font-medium">{email}</span>, we&apos;ve sent a reset link.
              Check your inbox — the link expires in 1 hour.
            </p>
            <button
              type="button"
              onClick={() => switchMode("login")}
              className="self-start text-sm font-medium text-accent hover:underline"
            >
              Back to login
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-zinc-500" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-background"
              />
            </div>
            {mode !== "forgot" && (
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-medium text-zinc-500" htmlFor="password">
                    Password
                  </label>
                  {mode === "login" && (
                    <button
                      type="button"
                      onClick={() => switchMode("forgot")}
                      className="text-xs font-medium text-accent hover:underline"
                    >
                      Forgot password?
                    </button>
                  )}
                </div>
                <input
                  id="password"
                  type="password"
                  required
                  minLength={mode === "signup" ? 8 : undefined}
                  autoComplete={mode === "signup" ? "new-password" : "current-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-background"
                />
                {mode === "signup" && <p className="text-xs text-zinc-400">At least 8 characters.</p>}
              </div>
            )}
            {mode === "signup" && signupRequiresCode && (
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-zinc-500" htmlFor="signup_code">
                  Invite code
                </label>
                <input
                  id="signup_code"
                  required
                  value={signupCode}
                  onChange={(e) => setSignupCode(e.target.value)}
                  className="rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-background"
                />
              </div>
            )}
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
              {busy ? "Working…" : mode === "forgot" ? "Send reset link" : mode === "signup" ? "Create account" : "Log in"}
            </button>
            {mode === "forgot" && (
              <button
                type="button"
                onClick={() => switchMode("login")}
                className="self-center text-xs font-medium text-zinc-500 hover:underline"
              >
                Back to login
              </button>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
