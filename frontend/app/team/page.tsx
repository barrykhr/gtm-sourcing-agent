"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  ApiError,
  ConversionCounts,
  IntegrationStatus,
  RecruiterRevenue,
  RecruiterUsage,
  RecruiterVelocity,
  TeamMember,
  TeamUsage,
  VelocityReport,
  getIntegrationsStatus,
  getRevenueByRecruiter,
  getTeamUsage,
  getTeamVelocity,
  listUsers,
  setUserRole,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ProgressBar } from "@/components/ui/ProgressBar";

function rate(numerator: number, denominator: number): string {
  if (denominator === 0) return "—";
  return `${Math.round((numerator / denominator) * 100)}%`;
}

// Short label for a chart x-axis tick — the part of the email before the
// @, so a wide team doesn't force the axis to wrap or overlap.
function shortLabel(email: string): string {
  return email.split("@")[0];
}

const CHART_TOOLTIP_STYLE = {
  contentStyle: {
    backgroundColor: "var(--surface-raised)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    fontSize: 12,
  },
  labelStyle: { color: "var(--foreground)", fontWeight: 600 },
  itemStyle: { color: "var(--foreground)" },
};

function ChartCard({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-surface p-4 shadow-[var(--shadow-sm)] dark:border-zinc-800">
      <h3 className="text-sm font-semibold text-zinc-500">{title}</h3>
      <p className="mt-0.5 mb-3 text-xs text-zinc-400">{subtitle}</p>
      <div className="h-64 w-full">{children}</div>
    </div>
  );
}

function ActivityByRecruiterChart({ recruiters }: { recruiters: RecruiterUsage[] }) {
  const data = [...recruiters]
    .sort((a, b) => b.total_actions - a.total_actions)
    .map((r) => ({ recruiter: shortLabel(r.email), "Total actions": r.total_actions, Placements: r.placements }));
  return (
    <ChartCard title="Activity by recruiter" subtitle="Lifetime actions logged vs. placements made.">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="recruiter" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
          <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} allowDecimals={false} />
          <Tooltip {...CHART_TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="Total actions" fill="var(--accent-soft)" stroke="var(--accent)" radius={[4, 4, 0, 0]} />
          <Bar dataKey="Placements" fill="var(--success)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

// Large revenue figures (6-7 digits) need a compact axis label — "333k"
// instead of "333200" — or they get clipped against the chart's edge.
function compactNumber(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 1 })}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toLocaleString(undefined, { maximumFractionDigits: 1 })}k`;
  return `${value}`;
}

function RevenueByRecruiterChart({ revenue }: { revenue: RecruiterRevenue[] }) {
  const data = [...revenue]
    .sort((a, b) => b.total_revenue - a.total_revenue)
    .map((r) => ({ recruiter: shortLabel(r.email), Expected: r.expected_revenue, Realized: r.realized_revenue }));
  return (
    <ChartCard title="Revenue by recruiter" subtitle="Expected (priced, open) stacked with realized (actual placement fees).">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="recruiter" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
          <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} tickFormatter={compactNumber} width={40} />
          <Tooltip {...CHART_TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="Realized" stackId="revenue" fill="var(--success)" radius={[0, 0, 0, 0]} />
          <Bar dataKey="Expected" stackId="revenue" fill="var(--accent-soft)" stroke="var(--accent)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function ConversionByRecruiterChart({ recruiters }: { recruiters: RecruiterVelocity[] }) {
  const data = recruiters.map((r) => ({
    recruiter: shortLabel(r.email),
    Sourced: r.conversion.sourced,
    "A-tier": r.conversion.tiered_a,
    Pursued: r.conversion.pursued,
    Placed: r.conversion.placed,
  }));
  return (
    <ChartCard title="Conversion funnel by recruiter" subtitle="Where candidates drop off, per recruiter.">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="recruiter" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
          <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} allowDecimals={false} />
          <Tooltip {...CHART_TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="Sourced" fill="var(--accent-soft)" stroke="var(--accent)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="A-tier" fill="var(--accent)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="Pursued" fill="var(--warning)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="Placed" fill="var(--success)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
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

// Role management (production-readiness phase) — admin-only, hidden
// here for a non-admin purely as UX (the server enforces this for real
// via require_role("admin"); this component never assumes the frontend
// check is the actual boundary). A recruiter simply doesn't see this
// section; they'd still get a 403 if they somehow called the API.
function RoleManagementPanel() {
  const { user } = useAuth();
  const [members, setMembers] = useState<TeamMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    if (user?.role !== "admin") return;
    listUsers()
      .then(setMembers)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load accounts."));
  }, [user?.role]);

  if (user?.role !== "admin") return null;

  async function changeRole(memberId: string, role: "admin" | "recruiter") {
    setBusyId(memberId);
    setError(null);
    try {
      const updated = await setUserRole(memberId, role);
      setMembers((prev) => prev?.map((m) => (m.id === memberId ? updated : m)) ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not update role.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <h2 className="font-display text-xl tracking-tight">Accounts &amp; roles</h2>
      <p className="mt-1 text-sm text-muted-foreground">Admin-only. Every account still sees the same jobs and candidates — role only controls who can manage other accounts.</p>
      {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
      {members === null ? (
        <p className="mt-3 text-sm text-zinc-500">Loading…</p>
      ) : (
        <div className="mt-3 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full min-w-[420px] text-left text-sm">
            <thead className="border-b border-zinc-200 text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800">
              <tr>
                <th className="px-4 py-2.5 font-medium">Email</th>
                <th className="px-4 py-2.5 font-medium">Role</th>
                <th className="px-4 py-2.5 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                  <td className="px-4 py-2.5 font-medium">{m.email}{m.id === user?.id && <span className="ml-1.5 text-xs font-normal text-zinc-400">(you)</span>}</td>
                  <td className="px-4 py-2.5 capitalize">{m.role}</td>
                  <td className="px-4 py-2.5">
                    {m.id !== user?.id && (
                      <button
                        onClick={() => changeRole(m.id, m.role === "admin" ? "recruiter" : "admin")}
                        disabled={busyId === m.id}
                        className="rounded-md border border-zinc-300 px-2.5 py-1 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                      >
                        {busyId === m.id ? "Saving…" : m.role === "admin" ? "Make recruiter" : "Make admin"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// Integration foundations (Google Workspace / Calendly / phone) — this
// is genuinely not connected to anything: no OAuth apps or telephony
// credentials exist in this environment. The point of this panel is to
// show the correct connection state and architecture honestly rather
// than fake a "Connected" state, per the product's explicit no-fake-
// integrations principle.
function IntegrationsPanel() {
  const [statuses, setStatuses] = useState<IntegrationStatus[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    getIntegrationsStatus().then(setStatuses).catch(() => setStatuses([]));
  }, []);

  if (!statuses || statuses.length === 0) return null;

  return (
    <div>
      <h2 className="font-display text-xl tracking-tight">Integrations</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Connect external tools to bring scheduling, meetings, and calls into Talyn. None of these are connected yet.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {statuses.map((s) => (
          <div key={s.provider} className="rounded-lg border border-zinc-200 bg-surface p-4 shadow-[var(--shadow-sm)] dark:border-zinc-800">
            <div className="flex items-center justify-between">
              <p className="font-medium">{s.label}</p>
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                Not connected
              </span>
            </div>
            <p className="mt-1.5 text-xs text-zinc-500">{s.capabilities}</p>
            <button
              onClick={() =>
                setNotice(
                  `${s.label} isn't connected yet. Connecting it requires a real ${
                    s.provider === "google_workspace" ? "Google Cloud OAuth app" : s.provider === "calendly" ? "Calendly OAuth app" : "telephony provider (e.g. Twilio) account"
                  } — this environment doesn't have one configured.`
                )
              }
              className="mt-3 rounded-md border border-zinc-300 px-2.5 py-1 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Connect {s.label}
            </button>
          </div>
        ))}
      </div>
      {notice && (
        <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          {notice}
        </p>
      )}
    </div>
  );
}

export default function TeamUsagePage() {
  const [usage, setUsage] = useState<TeamUsage | null>(null);
  const [velocity, setVelocity] = useState<VelocityReport | null>(null);
  const [revenueByRecruiter, setRevenueByRecruiter] = useState<RecruiterRevenue[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTeamUsage()
      .then(setUsage)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not reach the API."));
    getTeamVelocity()
      .then(setVelocity)
      .catch(() => {}); // non-critical — the usage tables above are the page's core content
    getRevenueByRecruiter()
      .then(setRevenueByRecruiter)
      .catch(() => {}); // non-critical — revenue may not be priced on any roles yet
  }, []);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="eyebrow mb-1.5">Recruiter performance</p>
        <h1 className="font-display text-4xl tracking-tight">Team</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
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
              {(usage.recruiters.some((r) => r.total_actions > 0) ||
                (revenueByRecruiter && revenueByRecruiter.length > 0) ||
                (velocity && velocity.by_recruiter.length > 0)) && (
                <div>
                  <h2 className="text-sm font-semibold text-zinc-500">Performance charts</h2>
                  <p className="mt-0.5 mb-2 text-xs text-zinc-400">
                    The same numbers as the tables below, visualized for a quick comparison across the team.
                  </p>
                  <div className="grid gap-4 lg:grid-cols-2">
                    <ActivityByRecruiterChart recruiters={usage.recruiters} />
                    {revenueByRecruiter && revenueByRecruiter.length > 0 && (
                      <RevenueByRecruiterChart revenue={revenueByRecruiter} />
                    )}
                    {velocity && velocity.by_recruiter.length > 0 && (
                      <ConversionByRecruiterChart recruiters={velocity.by_recruiter} />
                    )}
                  </div>
                </div>
              )}

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

              {revenueByRecruiter && revenueByRecruiter.length > 0 && (
                <div>
                  <h2 className="text-sm font-semibold text-zinc-500">Revenue by recruiter</h2>
                  <p className="mt-0.5 mb-2 text-xs text-zinc-400">
                    Every recruiter attributed to a role — primary or contributor — gets full credit for that
                    role&apos;s revenue, so shares can add up to more than 100% of the firm total across contributors.
                  </p>
                  <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-surface shadow-[var(--shadow-sm)] dark:border-zinc-800">
                    <table className="w-full min-w-[640px] border-collapse text-sm">
                      <thead>
                        <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800">
                          <th className="px-4 py-3 font-medium">Recruiter</th>
                          <th className="px-4 py-3 font-medium">Roles</th>
                          <th className="px-4 py-3 font-medium">Expected</th>
                          <th className="px-4 py-3 font-medium">Realized</th>
                          <th className="px-4 py-3 font-medium">Total</th>
                          <th className="px-4 py-3 font-medium">Share of firm</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...revenueByRecruiter]
                          .sort((a, b) => b.total_revenue - a.total_revenue)
                          .map((r) => (
                            <tr key={r.email} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                              <td className="px-4 py-3 font-medium">{r.email}</td>
                              <td className="px-4 py-3 tabular-nums">{r.roles}</td>
                              <td className="px-4 py-3 tabular-nums">{r.expected_revenue.toLocaleString()}</td>
                              <td className="px-4 py-3 tabular-nums">{r.realized_revenue.toLocaleString()}</td>
                              <td className="px-4 py-3 font-medium tabular-nums">{r.total_revenue.toLocaleString()}</td>
                              <td className="px-4 py-3">
                                <div className="flex flex-col gap-1">
                                  <span className="tabular-nums text-xs">{Math.round(r.share_of_firm)}%</span>
                                  <ProgressBar value={r.share_of_firm} max={100} />
                                </div>
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

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

          <RoleManagementPanel />

          <IntegrationsPanel />

          <p className="text-xs text-zinc-400">
            The usage/performance data above is visible to every account. Only the Accounts &amp; roles section is admin-only.
          </p>
        </>
      ) : null}
    </div>
  );
}
