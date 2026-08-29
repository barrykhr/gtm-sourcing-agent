"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AnalyticsOverview,
  ApiError,
  AttentionNeeded,
  CLOSED_LIFECYCLE_STATUSES,
  JOB_LIFECYCLE_LABELS,
  RevenueOverview,
  createJob,
  getAnalyticsOverview,
  getAttentionNeeded,
  getRevenueOverview,
  JobSummary,
  listJobs,
} from "@/lib/api";
import { StatusChip } from "@/components/StatusChip";
import { useAuth } from "@/lib/auth-context";

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-surface px-4 py-3.5 shadow-xs">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

const STAGE_LABELS: Record<string, string> = {
  intake: "JD analysed",
  calibration: "Calibrated",
  icp: "Hiring profile",
  talent_map: "Talent map",
  search_strategy: "Sourcing strategy",
};

function jobProgress(job: JobSummary): { done: number; total: number } {
  const values = Object.values(job.status);
  return { done: values.filter(Boolean).length, total: values.length };
}

// Daily digest email handoff (Phase 8) — built entirely from data the
// dashboard already fetched (overview + attention), so no new backend
// endpoint. Same mailto: pattern as the outreach email handoff: a real
// pre-filled draft, recipient left for the recruiter to fill in.
function digestMailto(overview: AnalyticsOverview | null, attention: AttentionNeeded | null): string {
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  const lines: string[] = [`Recruiting digest — ${today}`, ""];
  if (overview) {
    lines.push(
      `${overview.total_jobs} open jobs · ${overview.total_candidates} candidates · ` +
        `${overview.decisions_recorded}/${overview.decisions_recorded + overview.decisions_pending} decisions recorded`,
      ""
    );
  }
  if (attention && attention.needs_follow_up.length > 0) {
    lines.push(`Needs follow-up (${attention.needs_follow_up.length}):`);
    attention.needs_follow_up.forEach((i) =>
      lines.push(`  - ${i.candidate_name} — ${i.job_title} · ${i.current_stage.replace(/_/g, " ")} · ${i.days_in_stage}d`)
    );
    lines.push("");
  }
  if (attention && attention.upcoming_interviews.length > 0) {
    lines.push(`Upcoming interviews (${attention.upcoming_interviews.length}):`);
    attention.upcoming_interviews.forEach((i) =>
      lines.push(`  - ${i.candidate_name} — ${i.job_title} · ${new Date(i.scheduled_at).toLocaleString()}`)
    );
  }
  return `mailto:?subject=${encodeURIComponent(`Recruiting digest — ${today}`)}&body=${encodeURIComponent(lines.join("\n"))}`;
}

export default function Dashboard() {
  const router = useRouter();
  const { user } = useAuth();
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [attention, setAttention] = useState<AttentionNeeded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [roleFamily, setRoleFamily] = useState("");
  const [clientName, setClientName] = useState("");
  const [roleValue, setRoleValue] = useState("");
  const [revenue, setRevenue] = useState<RevenueOverview | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const [myJobsOnly, setMyJobsOnly] = useState(false);
  const [clientFilter, setClientFilter] = useState("");

  const refresh = () => {
    listJobs()
      .then(setJobs)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not reach the API."));
    getAnalyticsOverview()
      .then(setOverview)
      .catch(() => {}); // non-critical — the job list above is the page's core content
    getAttentionNeeded()
      .then(setAttention)
      .catch(() => {});
    getRevenueOverview()
      .then(setRevenue)
      .catch(() => {}); // non-critical — role values are optional, this section just doesn't render without them
  };

  useEffect(refresh, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const parsedValue = roleValue.trim() ? Number(roleValue.trim()) : null;
      const job = await createJob(title.trim(), roleFamily.trim(), undefined, clientName.trim(), parsedValue);
      router.push(`/jobs/${job.role_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create the job.");
      setCreating(false);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-end justify-between">
        <div>
          <p className="eyebrow mb-1.5">Recruiting workspace</p>
          <h1 className="font-display text-4xl tracking-tight">Jobs</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">Every hiring assignment is a persistent workspace.</p>
        </div>
      </div>

      {overview && overview.total_jobs > 0 && (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Jobs" value={overview.total_jobs} />
            <StatCard label="Candidates" value={overview.total_candidates} />
            <StatCard label="Evaluations" value={overview.total_evaluations} />
            <StatCard
              label="Decisions recorded"
              value={`${overview.decisions_recorded}/${overview.decisions_recorded + overview.decisions_pending}`}
            />
          </div>
          <p className="text-xs text-zinc-500">
            Tier —{" "}
            {(["A", "B", "C", "D"] as const)
              .map((t) => `${t} ${overview.tier_distribution[t]}`)
              .join(" · ")}
            {overview.tier_distribution.not_prioritized > 0 &&
              ` · not yet prioritized ${overview.tier_distribution.not_prioritized}`}
          </p>
        </div>
      )}

      {revenue && (revenue.open_roles_priced > 0 || revenue.realized_revenue > 0) && (
        <div className="flex flex-col gap-1.5">
          <p className="eyebrow">Cumulative revenue</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Open positions" value={revenue.open_roles} />
            <StatCard label="Expected revenue" value={revenue.expected_revenue.toLocaleString()} />
            <StatCard label="Revenue in pipeline" value={revenue.pipeline_revenue.toLocaleString()} />
            <StatCard label="Realized" value={revenue.realized_revenue.toLocaleString()} />
          </div>
          <p className="text-xs text-muted-foreground">
            Expected = {revenue.open_roles_priced} priced open role{revenue.open_roles_priced === 1 ? "" : "s"} ×{" "}
            {revenue.margin_percentage}% margin. Realized is actual placement fees, not an estimate.
          </p>
        </div>
      )}

      {attention && (attention.needs_follow_up.length > 0 || attention.upcoming_interviews.length > 0) && (
        <div className="flex flex-col gap-3">
          <a
            href={digestMailto(overview, attention)}
            className="self-end rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Email digest
          </a>
          <div className="grid gap-4 sm:grid-cols-2">
          {attention.needs_follow_up.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950">
              <h2 className="text-sm font-semibold text-amber-800 dark:text-amber-400">
                Needs follow-up ({attention.needs_follow_up.length})
              </h2>
              <ul className="mt-2 flex flex-col gap-1.5">
                {attention.needs_follow_up.slice(0, 6).map((item) => (
                  <li key={`${item.role_id}-${item.candidate_id}`}>
                    <button
                      onClick={() => router.push(`/jobs/${item.role_id}`)}
                      className="text-left text-sm hover:underline"
                    >
                      <span className="font-medium">{item.candidate_name}</span>
                      <span className="text-xs text-zinc-500">
                        {" "}
                        — {item.job_title} · {item.current_stage.replace(/_/g, " ")} · {item.days_in_stage}d
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {attention.upcoming_interviews.length > 0 && (
            <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-900 dark:bg-indigo-950">
              <h2 className="text-sm font-semibold text-indigo-800 dark:text-indigo-400">
                Upcoming interviews ({attention.upcoming_interviews.length})
              </h2>
              <ul className="mt-2 flex flex-col gap-1.5">
                {attention.upcoming_interviews.slice(0, 6).map((item) => (
                  <li key={`${item.role_id}-${item.candidate_id}`}>
                    <button
                      onClick={() => router.push(`/jobs/${item.role_id}`)}
                      className="text-left text-sm hover:underline"
                    >
                      <span className="font-medium">{item.candidate_name}</span>
                      <span className="text-xs text-zinc-500">
                        {" "}
                        — {item.job_title} ·{" "}
                        {new Date(item.scheduled_at).toLocaleString(undefined, {
                          month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
                        })}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          </div>
        </div>
      )}

      <form
        onSubmit={handleCreate}
        className="flex flex-wrap items-end gap-3 rounded-lg border border-zinc-200 bg-surface p-4 shadow-[var(--shadow-sm)] dark:border-zinc-800"
      >
        <div className="flex flex-1 min-w-48 flex-col gap-1">
          <label className="text-xs font-medium text-zinc-500" htmlFor="title">
            Role title
          </label>
          <input
            id="title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Enterprise AE — Acme"
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-zinc-500" htmlFor="role_family">
            Role family
          </label>
          <input
            id="role_family"
            value={roleFamily}
            onChange={(e) => setRoleFamily(e.target.value)}
            placeholder="sales, csm, sdr, engineering…"
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-zinc-500" htmlFor="client_name">
            Client
          </label>
          <input
            id="client_name"
            value={clientName}
            onChange={(e) => setClientName(e.target.value)}
            placeholder="optional — which client this role is for"
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
          />
        </div>
        <div className="flex w-36 flex-col gap-1">
          <label className="text-xs font-medium text-zinc-500" htmlFor="role_value">
            Role value / CTC
          </label>
          <input
            id="role_value"
            value={roleValue}
            onChange={(e) => setRoleValue(e.target.value)}
            inputMode="decimal"
            placeholder="optional"
            title="Annual CTC or fee basis — 8.33% of this becomes Expected Revenue"
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-600 dark:border-zinc-700 dark:bg-zinc-950"
          />
        </div>
        <button
          type="submit"
          disabled={creating || !title.trim()}
          className="rounded-md bg-indigo-700 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-800 disabled:opacity-50"
        >
          {creating ? "Creating…" : "New job"}
        </button>
      </form>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
          {error}
        </div>
      )}

      {jobs && jobs.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setMyJobsOnly((v) => !v)}
            className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
              myJobsOnly
                ? "border-indigo-600 bg-indigo-50 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-400"
                : "border-zinc-300 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            }`}
          >
            My jobs
          </button>
          <button
            onClick={() => setShowClosed((v) => !v)}
            className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
              showClosed
                ? "border-indigo-600 bg-indigo-50 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-400"
                : "border-zinc-300 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            }`}
          >
            Show closed jobs
          </button>
          {(() => {
            const clients = [...new Set(jobs.map((j) => j.client_name).filter((c): c is string => Boolean(c)))].sort();
            if (clients.length === 0) return null;
            return (
              <select
                value={clientFilter}
                onChange={(e) => setClientFilter(e.target.value)}
                className="rounded-md border border-zinc-300 bg-surface px-2.5 py-1.5 text-xs font-medium outline-none focus:border-indigo-600 dark:border-zinc-700"
              >
                <option value="">All clients</option>
                {clients.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            );
          })()}
        </div>
      )}

      {jobs === null && !error ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : jobs && jobs.length === 0 ? (
        <p className="text-sm text-zinc-500">No jobs yet — create one above to get started.</p>
      ) : (
        (() => {
          const visible = (jobs ?? [])
            .filter((j) => showClosed || !CLOSED_LIFECYCLE_STATUSES.includes(j.lifecycle_status))
            .filter((j) => !myJobsOnly || j.owner_email === user?.email)
            .filter((j) => !clientFilter || j.client_name === clientFilter);
          if (visible.length === 0) {
            return <p className="text-sm text-zinc-500">No jobs match these filters.</p>;
          }
          return (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((job) => {
            const { done, total } = jobProgress(job);
            return (
              <button
                key={job.role_id}
                onClick={() => router.push(`/jobs/${job.role_id}`)}
                className="flex flex-col gap-3 rounded-lg border border-zinc-200 bg-surface p-4 text-left shadow-[var(--shadow-sm)] transition hover:border-indigo-600 hover:shadow-[var(--shadow-md)] dark:border-zinc-800"
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="font-medium">{job.title}</h2>
                    {job.lifecycle_status !== "OPEN" && (
                      <span className="shrink-0 rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-500 dark:bg-zinc-800">
                        {JOB_LIFECYCLE_LABELS[job.lifecycle_status]}
                      </span>
                    )}
                  </div>
                  {job.role_family && <p className="text-xs text-zinc-500">{job.role_family}</p>}
                  {job.client_name && (
                    <p className="text-xs font-medium text-indigo-700 dark:text-indigo-400">{job.client_name}</p>
                  )}
                  {job.owner_email && job.owner_email !== user?.email && (
                    <p className="text-xs text-zinc-400">Owner: {job.owner_email}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <StatusChip
                    label={`${done}/${total} stages`}
                    variant={done === total ? "ok" : done === 0 ? "pending" : "running"}
                  />
                  {job.next_stage && (
                    <span className="text-xs text-zinc-500">
                      next: {STAGE_LABELS[job.next_stage] ?? job.next_stage}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
          );
        })()
      )}
    </div>
  );
}
