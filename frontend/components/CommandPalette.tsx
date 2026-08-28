"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Briefcase, Search, User } from "lucide-react";
import { search, SearchResult } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const DEBOUNCE_MS = 200;

/** ⌘K / Ctrl+K command palette (Phase 11 design pass) — replaces a
 * header search box with the pattern enterprise SaaS tools (Linear,
 * Vercel, Raycast) converged on: a keyboard shortcut summons a centered
 * overlay, type to filter, Escape or a click outside dismisses it. Same
 * search() API underneath as before; this only changes the container. */
export function CommandPalette() {
  const router = useRouter();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const openRef = useRef(false);
  useEffect(() => {
    openRef.current = open;
  }, [open]);

  function openPalette() {
    setQuery("");
    setResult(null);
    setOpen(true);
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (openRef.current) setOpen(false);
        else openPalette();
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    // Focus is a DOM/external-system effect, not React state — the one
    // thing an effect here is actually for.
    if (open) requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) return;
    const timer = setTimeout(() => {
      search(trimmed).then(setResult).catch(() => setResult(null));
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  function go(path: string) {
    setOpen(false);
    router.push(path);
  }

  if (!user) return null;

  const hasQuery = query.trim().length > 0;
  const hasResults = result && (result.jobs.length > 0 || result.candidates.length > 0);

  return (
    <>
      <button
        onClick={openPalette}
        className="flex w-full items-center gap-2 rounded-md border border-[var(--border)] bg-background px-3 py-2 text-sm text-zinc-500 hover:border-zinc-300 dark:hover:border-zinc-700"
      >
        <Search size={15} className="shrink-0" />
        <span className="flex-1 text-left">Search…</span>
        <kbd className="rounded border border-[var(--border)] bg-surface px-1.5 py-0.5 text-[10px] font-medium text-zinc-400">
          ⌘K
        </kbd>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-zinc-950/40 px-4 pt-[15vh] backdrop-blur-[1px]"
          onClick={() => setOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-lg overflow-hidden rounded-xl border border-[var(--border)] bg-surface shadow-[var(--shadow-lg)]"
          >
            <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
              <Search size={16} className="shrink-0 text-zinc-400" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search jobs or candidates…"
                aria-label="Search jobs or candidates"
                className="w-full bg-transparent text-sm outline-none placeholder:text-zinc-400"
              />
              <kbd className="rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px] font-medium text-zinc-400">
                esc
              </kbd>
            </div>

            <div className="max-h-80 overflow-y-auto p-2">
              {!hasQuery ? (
                <p className="px-2 py-6 text-center text-sm text-zinc-400">Start typing to search the workspace.</p>
              ) : !hasResults ? (
                <p className="px-2 py-6 text-center text-sm text-zinc-400">No matches.</p>
              ) : (
                <>
                  {result!.jobs.length > 0 && (
                    <div className="mb-1">
                      <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">Jobs</p>
                      {result!.jobs.map((j) => (
                        <button
                          key={j.role_id}
                          onClick={() => go(`/jobs/${j.role_id}`)}
                          className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left text-sm hover:bg-background"
                        >
                          <Briefcase size={15} className="shrink-0 text-zinc-400" />
                          <span className="truncate">{j.title}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {result!.candidates.length > 0 && (
                    <div>
                      <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">Candidates</p>
                      {result!.candidates.map((c) => (
                        <button
                          key={c.candidate_id}
                          onClick={() => go(`/candidates/${c.candidate_id}`)}
                          className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left text-sm hover:bg-background"
                        >
                          <User size={15} className="shrink-0 text-zinc-400" />
                          <span className="truncate">
                            {c.name}
                            {c.current_title && (
                              <span className="text-zinc-400"> — {c.current_title}{c.current_company ? ` @ ${c.current_company}` : ""}</span>
                            )}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
