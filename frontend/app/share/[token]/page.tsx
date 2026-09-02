"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, FUNNEL_STAGES, PublicRoleSummary, getPublicRoleSummary } from "@/lib/api";

/** Client-facing status page (Batch B) — the one page in this product
 * meant for someone outside the recruiting team. No login, no sidebar
 * (see AppShell). get_public_role_summary always returns counts/stage
 * names; per-candidate detail appears only for candidates the recruiter
 * has explicitly opted into sharing (client_visible), and even then only
 * the safe subset — never CTC, contact info, private notes, or internal
 * recruiter assessment (see db_storage.get_public_role_summary's
 * docstring for the exact allow-list). */
export default function PublicRoleStatus() {
  const params = useParams<{ token: string }>();
  const [summary, setSummary] = useState<PublicRoleSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPublicRoleSummary(params.token)
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load this link."));
  }, [params.token]);

  if (error) {
    return (
      <div className="w-full max-w-md text-center">
        <p className="text-sm text-zinc-500">{error}</p>
      </div>
    );
  }
  if (!summary) {
    return <p className="text-sm text-zinc-500">Loading…</p>;
  }

  const totalInPipeline = Object.values(summary.counts_by_stage).reduce((a, b) => a + b, 0);

  return (
    <div className="w-full max-w-xl">
      <div className="rounded-xl border border-zinc-200 bg-surface p-6 shadow-[var(--shadow-md)] dark:border-zinc-800">
        {summary.client_name && (
          <p className="text-xs font-medium uppercase tracking-wide text-indigo-700 dark:text-indigo-400">
            {summary.client_name}
          </p>
        )}
        <h1 className="mt-1 text-xl font-semibold tracking-tight">{summary.title}</h1>
        <p className="mt-1 text-xs text-zinc-500">
          Status: {summary.lifecycle_status.replace("_", " ").toLowerCase()} · updated{" "}
          {new Date(summary.updated_at).toLocaleDateString()}
        </p>

        <div className="mt-5 flex gap-3">
          <div className="rounded-lg border border-zinc-200 bg-background px-4 py-3 dark:border-zinc-800">
            <p className="text-xs uppercase tracking-wide text-zinc-500">Candidates sourced</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{summary.total_candidates}</p>
          </div>
          <div className="rounded-lg border border-zinc-200 bg-background px-4 py-3 dark:border-zinc-800">
            <p className="text-xs uppercase tracking-wide text-zinc-500">In active pipeline</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{totalInPipeline}</p>
          </div>
        </div>

        <div className="mt-5">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Pipeline stage</p>
          <div className="flex flex-col gap-1.5">
            {FUNNEL_STAGES.filter((s) => summary.counts_by_stage[s] > 0).map((stage) => (
              <div key={stage} className="flex items-center justify-between text-sm">
                <span className="text-zinc-600 dark:text-zinc-400">{stage.replace(/_/g, " ")}</span>
                <span className="font-medium tabular-nums">{summary.counts_by_stage[stage]}</span>
              </div>
            ))}
            {totalInPipeline === 0 && <p className="text-sm text-zinc-400">No candidates in the pipeline yet.</p>}
          </div>
        </div>

        {summary.shared_candidates.length > 0 && (
          <div className="mt-6 border-t border-zinc-200 pt-5 dark:border-zinc-800">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500">Candidates shared with you</p>
            <div className="flex flex-col gap-3">
              {summary.shared_candidates.map((c, i) => (
                <div key={i} className="rounded-lg border border-zinc-200 bg-background p-3 dark:border-zinc-800">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-sm font-semibold">{c.name}</p>
                    <span className="shrink-0 text-xs text-zinc-500">{c.current_stage.replace(/_/g, " ").toLowerCase()}</span>
                  </div>
                  <p className="text-xs text-zinc-500">
                    {c.current_title}{c.current_company && ` @ ${c.current_company}`}
                    {c.location && ` · ${c.location}`}
                  </p>
                  {c.why_they_fit && c.why_they_fit.length > 0 && (
                    <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-zinc-600 dark:text-zinc-400">
                      {c.why_they_fit.map((w, wi) => <li key={wi}>{w}</li>)}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <p className="mt-4 text-center text-xs text-zinc-400">
        Shared read-only view — only candidates your recruiter has explicitly shared appear above; everything else stays private.
      </p>
    </div>
  );
}
