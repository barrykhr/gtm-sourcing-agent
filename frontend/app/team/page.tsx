"use client";

import { useEffect, useState } from "react";
import { ApiError, TeamUsage, getTeamUsage } from "@/lib/api";

export default function TeamUsagePage() {
  const [usage, setUsage] = useState<TeamUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTeamUsage()
      .then(setUsage)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not reach the API."));
  }, []);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Team</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Every recruiter with an account, and what they&apos;ve actually done in this workspace.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
          {error}
        </div>
      )}

      {usage === null && !error ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : usage ? (
        <>
          <div className="flex flex-wrap gap-3">
            <div className="rounded-lg border border-zinc-200 bg-surface px-4 py-3 shadow-[var(--shadow-sm)] dark:border-zinc-800">
              <p className="text-xs uppercase tracking-wide text-zinc-500">Accounts</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{usage.total_users}</p>
            </div>
            <div className="rounded-lg border border-zinc-200 bg-surface px-4 py-3 shadow-[var(--shadow-sm)] dark:border-zinc-800">
              <p className="text-xs uppercase tracking-wide text-zinc-500">Total actions logged</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {usage.recruiters.reduce((sum, r) => sum + r.total_actions, 0)}
              </p>
            </div>
            <div className="rounded-lg border border-zinc-200 bg-surface px-4 py-3 shadow-[var(--shadow-sm)] dark:border-zinc-800">
              <p className="text-xs uppercase tracking-wide text-zinc-500">Placements</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {usage.recruiters.reduce((sum, r) => sum + r.placements, 0)}
              </p>
            </div>
            <div className="rounded-lg border border-zinc-200 bg-surface px-4 py-3 shadow-[var(--shadow-sm)] dark:border-zinc-800">
              <p className="text-xs uppercase tracking-wide text-zinc-500">Total fees</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {usage.recruiters
                  .reduce((sum, r) => sum + r.placement_fees, 0)
                  .toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 })}
              </p>
            </div>
          </div>

          {usage.recruiters.length === 0 ? (
            <p className="text-sm text-zinc-500">No accounts yet.</p>
          ) : (
            <>
              <div>
                <h2 className="text-sm font-semibold text-zinc-500">Current load</h2>
                <p className="mt-0.5 mb-2 text-xs text-zinc-400">
                  Right now, not lifetime — open searches and candidates still active in them.
                </p>
                <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-surface shadow-[var(--shadow-sm)] dark:border-zinc-800">
                  <table className="w-full min-w-[420px] border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800">
                        <th className="px-4 py-3 font-medium">Recruiter</th>
                        <th className="px-4 py-3 font-medium">Open jobs</th>
                        <th className="px-4 py-3 font-medium">Active candidates</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...usage.recruiters]
                        .sort((a, b) => b.active_candidates - a.active_candidates)
                        .map((r) => (
                          <tr key={r.email} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                            <td className="px-4 py-3 font-medium">{r.email}</td>
                            <td className="px-4 py-3 tabular-nums">{r.open_jobs}</td>
                            <td className="px-4 py-3 tabular-nums">{r.active_candidates}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div>
                <h2 className="text-sm font-semibold text-zinc-500">Activity &amp; results</h2>
                <p className="mt-0.5 mb-2 text-xs text-zinc-400">Lifetime totals across every job, open or closed.</p>
                <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-surface shadow-[var(--shadow-sm)] dark:border-zinc-800">
                  <table className="w-full min-w-[640px] border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800">
                        <th className="px-4 py-3 font-medium">Recruiter</th>
                        <th className="px-4 py-3 font-medium">Jobs owned</th>
                        <th className="px-4 py-3 font-medium">Candidates added</th>
                        <th className="px-4 py-3 font-medium">Total actions</th>
                        <th className="px-4 py-3 font-medium">Placements</th>
                        <th className="px-4 py-3 font-medium">Fees</th>
                        <th className="px-4 py-3 font-medium">Last active</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.recruiters.map((r) => (
                        <tr key={r.email} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                          <td className="px-4 py-3">
                            <p className="font-medium">{r.email}</p>
                            <p className="text-xs text-zinc-500">joined {new Date(r.joined_at).toLocaleDateString()}</p>
                          </td>
                          <td className="px-4 py-3 tabular-nums">{r.jobs_owned}</td>
                          <td className="px-4 py-3 tabular-nums">{r.candidates_added}</td>
                          <td className="px-4 py-3 tabular-nums">{r.total_actions}</td>
                          <td className="px-4 py-3 tabular-nums">{r.placements}</td>
                          <td className="px-4 py-3 tabular-nums">
                            {r.placement_fees > 0
                              ? r.placement_fees.toLocaleString(undefined, {
                                  style: "currency", currency: "USD", maximumFractionDigits: 0,
                                })
                              : "—"}
                          </td>
                          <td className="px-4 py-3 text-zinc-500">
                            {r.last_active ? new Date(r.last_active).toLocaleString() : "never"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}

          <p className="text-xs text-zinc-400">
            Visible to every account — this workspace has no separate admin role, so any recruiter can see this page.
          </p>
        </>
      ) : null}
    </div>
  );
}
