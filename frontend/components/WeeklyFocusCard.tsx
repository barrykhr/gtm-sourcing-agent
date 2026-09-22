"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, WeeklyEffortPlan, requestWorkloadPlan } from "@/lib/api";

/** "This week's focus" (TAT/prioritization batch) — an AI judgment call on
 * how many days to spend on each open role this week, given each role's
 * urgency/TAT/deadline and the recruiter's own available capacity. A
 * recommendation the recruiter can override, never an automated schedule —
 * see stages/workload_planning.py's docstring. Self-service: every
 * recruiter plans against their own roster, not a team-wide view. */
export function WeeklyFocusCard() {
  const router = useRouter();
  const [availableDays, setAvailableDays] = useState("5");
  const [busy, setBusy] = useState(false);
  const [plan, setPlan] = useState<WeeklyEffortPlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function getPlan() {
    const days = Number(availableDays);
    if (!Number.isFinite(days) || days <= 0) {
      setError("Enter how many days you have available this week.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await requestWorkloadPlan(days);
      setPlan(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not generate a plan.");
    } finally {
      setBusy(false);
    }
  }

  const totalAllocated = plan?.allocations.reduce((sum, a) => sum + a.recommended_days_this_week, 0) ?? 0;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 bg-surface p-4 shadow-[var(--shadow-sm)] dark:border-zinc-800">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow mb-1">This week&apos;s focus</p>
          <p className="text-xs text-muted-foreground">
            A judgment call on how to split your time across your open roles this week — based on each role&apos;s
            urgency, how long it&apos;s been open, and any client deadline. A recommendation, not a schedule.
          </p>
        </div>
        <div className="flex shrink-0 items-end gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-zinc-500" htmlFor="available_days">
              Days available this week
            </label>
            <input
              id="available_days"
              value={availableDays}
              onChange={(e) => setAvailableDays(e.target.value)}
              inputMode="decimal"
              className="w-20 rounded-md border border-zinc-300 px-2 py-1.5 text-sm outline-none focus:border-signal-600 dark:border-zinc-700 dark:bg-zinc-950"
            />
          </div>
          <button
            onClick={getPlan}
            disabled={busy}
            className="rounded-md bg-signal-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-signal-800 disabled:opacity-50"
          >
            {busy ? "Thinking…" : plan ? "Regenerate" : "Get this week's plan"}
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-critical">{error}</p>}

      {plan && (
        plan.allocations.length === 0 ? (
          <p className="text-sm text-muted-foreground">No open roles to plan for right now.</p>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="divide-y divide-[var(--border-subtle)] rounded-md border border-[var(--border-subtle)]">
              {plan.allocations.map((a) => (
                <button
                  key={a.role_id}
                  onClick={() => router.push(`/jobs/${a.role_id}`)}
                  className="flex w-full flex-col gap-0.5 px-3 py-2.5 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium">{a.title}</span>
                    <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                      {a.recommended_days_this_week}d
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">{a.rationale}</p>
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {totalAllocated} of {plan.available_days_per_week} day{plan.available_days_per_week === 1 ? "" : "s"}{" "}
              allocated.
            </p>
            {plan.overall_notes && <p className="text-xs text-muted-foreground">{plan.overall_notes}</p>}
          </div>
        )
      )}
    </div>
  );
}
