"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  ConversionCounts,
  TeamUsage,
  VelocityReport,
  getTeamUsage,
  getTeamVelocity,
} from "@/lib/api";

function rate(numerator: number, denominator: number): string {
  if (denominator === 0) return "—";
  return `${Math.round((numerator / denominator) * 100)}%`;
}

function ConversionCell({ conversion }: { conversion: ConversionCounts }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="tabular-nums">
        {conversion.sourced} sourced → {conversion.tiered_a} A-tier → {conversion.pursued} pursued →{" "}
        {conversion.placed} placed
      </span>
      <span className="text-xs text-zinc-400">
        {rate(conversion.tiered_a, conversion.sourced)} tiered · {rate(conversion.pursued, conversion.tiered_a)} pursued ·{" "}
        {rate(conversion.placed, conversion.pursued)} placed
      </span>
    </div>
  );
}

function StageDaysCell({ avgDaysInStage }: { avgDaysInStage: Record<string, number> }) {
  const entries = Object.entries(avgDaysInStage);
  if (entries.length === 0) return <span className="text-xs text-zinc-400">no completed stage spans yet</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([stage, days]) => (
        <span
          key={stage}
          className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
        >
          {stage.replace(/_/g, " ")}: {days}d
        </span>
      ))}
    </div>
  );
}

export default function TeamUsagePage() {
  const [usage, setUsage] = useState<TeamUsage | null>(null);
  const [velocity, setVelocity] = useState<VelocityReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTeamUsage()
      .then(setUsage)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not reach the API."));
    getTeamVelocity()
      .then(setVelocity)
      .catch(() => {}); // non-critical — the usage tables above are the page's core content
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

              {velocity && (velocity.by_role.length > 0 || velocity.by_recruiter.length > 0) && (
                <div>
                  <h2 className="text-sm font-semibold text-zinc-500">Velocity &amp; conversion</h2>
                  <p className="mt-0.5 mb-2 text-xs text-zinc-400">
                    Is the effort converting, and where does it stall — cycle time only counts a stage once a
                    candidate has actually moved past it.
                  </p>

                  <div className="flex flex-col gap-4">
                    <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-surface shadow-[var(--shadow-sm)] dark:border-zinc-800">
                      <table className="w-full min-w-[720px] border-collapse text-sm">
                        <thead>
                          <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800">
                            <th className="px-4 py-3 font-medium">Role</th>
                            <th className="px-4 py-3 font-medium">Conversion</th>
                            <th className="px-4 py-3 font-medium">Avg days per completed stage</th>
                          </tr>
                        </thead>
                        <tbody>
                          {velocity.by_role.map((r) => (
                            <tr key={r.role_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                              <td className="px-4 py-3 font-medium">{r.title}</td>
                              <td className="px-4 py-3"><ConversionCell conversion={r.conversion} /></td>
                              <td className="px-4 py-3"><StageDaysCell avgDaysInStage={r.avg_days_in_stage} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {velocity.by_recruiter.length > 0 && (
                      <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-surface shadow-[var(--shadow-sm)] dark:border-zinc-800">
                        <table className="w-full min-w-[720px] border-collapse text-sm">
                          <thead>
                            <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800">
                              <th className="px-4 py-3 font-medium">Recruiter</th>
                              <th className="px-4 py-3 font-medium">Conversion</th>
                              <th className="px-4 py-3 font-medium">Avg days per completed stage</th>
                            </tr>
                          </thead>
                          <tbody>
                            {velocity.by_recruiter.map((r) => (
                              <tr key={r.email} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                                <td className="px-4 py-3 font-medium">{r.email}</td>
                                <td className="px-4 py-3"><ConversionCell conversion={r.conversion} /></td>
                                <td className="px-4 py-3"><StageDaysCell avgDaysInStage={r.avg_days_in_stage} /></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              )}
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
