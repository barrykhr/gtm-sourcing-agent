"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, CanonicalCandidate, listCandidatesGlobal } from "@/lib/api";
import { StatusChip, tierVariant } from "@/components/StatusChip";

type Tier = "A" | "B" | "C" | "D";
const TIER_ORDER: Tier[] = ["A", "B", "C", "D"];

function bestTier(evaluations: CanonicalCandidate["evaluations"]): Tier | null {
  const tiers = evaluations.map((e) => e.tier).filter((t): t is Tier => t !== null);
  if (tiers.length === 0) return null;
  return [...tiers].sort((a, b) => TIER_ORDER.indexOf(a) - TIER_ORDER.indexOf(b))[0];
}

export default function CandidatesRoster() {
  const router = useRouter();
  const [candidates, setCandidates] = useState<CanonicalCandidate[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCandidatesGlobal()
      .then(setCandidates)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not reach the API."));
  }, []);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="eyebrow mb-1.5">Talent pool</p>
        <h1 className="font-display text-4xl tracking-tight">Candidates</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Every person evaluated, across every job — one profile, one fit history.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
          {error}
        </div>
      )}

      {candidates === null && !error ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : candidates && candidates.length === 0 ? (
        <p className="text-sm text-zinc-500">No candidates yet — add one from a job&apos;s Candidates tab.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {candidates?.map((c) => (
            <button
              key={c.candidate_id}
              onClick={() => router.push(`/candidates/${c.candidate_id}`)}
              className="flex flex-col gap-3 rounded-lg border border-zinc-200 bg-surface p-4 text-left shadow-[var(--shadow-sm)] transition hover:border-indigo-600 hover:shadow-[var(--shadow-md)] dark:border-zinc-800"
            >
              <div>
                <h2 className="font-medium">{c.name}</h2>
                <p className="text-xs text-zinc-500">{c.current_title} @ {c.current_company}</p>
              </div>
              <div className="flex items-center gap-2">
                {bestTier(c.evaluations) && (
                  <StatusChip label={`Best: Tier ${bestTier(c.evaluations)}`} variant={tierVariant(bestTier(c.evaluations))} />
                )}
                <span className="text-xs text-zinc-500">
                  {c.evaluations.length} job{c.evaluations.length === 1 ? "" : "s"}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
