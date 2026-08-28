"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ApiError, CanonicalCandidate, getCandidateGlobal } from "@/lib/api";
import { StatusChip, tierVariant } from "@/components/StatusChip";

export default function CandidateDetail() {
  const params = useParams<{ candidate_id: string }>();
  const [candidate, setCandidate] = useState<CanonicalCandidate | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCandidateGlobal(params.candidate_id)
      .then(setCandidate)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not reach the API."));
  }, [params.candidate_id]);

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
        {error}
      </div>
    );
  }
  if (!candidate) return <p className="text-sm text-zinc-500">Loading…</p>;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link href="/candidates" className="text-sm text-indigo-700 hover:underline dark:text-indigo-400">
          ← Candidates
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">{candidate.name}</h1>
        <p className="mt-1 text-sm text-zinc-500">
          {candidate.current_title} @ {candidate.current_company}
          {candidate.location && ` · ${candidate.location}`}
        </p>
        {candidate.source_url && (
          <a
            href={candidate.source_url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block text-xs text-indigo-700 hover:underline dark:text-indigo-400"
          >
            {candidate.source_url}
          </a>
        )}
      </div>

      <div className="rounded-lg border border-zinc-200 bg-surface shadow-[var(--shadow-sm)] dark:border-zinc-800">
        <div className="border-b border-zinc-200 p-4 dark:border-zinc-800">
          <h2 className="text-sm font-semibold text-zinc-500">
            Evaluated for {candidate.evaluations.length} job{candidate.evaluations.length === 1 ? "" : "s"}
          </h2>
        </div>
        {candidate.evaluations.length === 0 ? (
          <p className="p-4 text-sm text-zinc-400">No evaluations yet.</p>
        ) : (
          <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {candidate.evaluations.map((e) => (
              <Link
                key={e.role_id}
                href={`/jobs/${e.role_id}`}
                className="flex items-center justify-between gap-3 p-4 hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
              >
                <div>
                  <p className="font-medium">{e.job_title}</p>
                  {e.why_they_fit && e.why_they_fit.length > 0 && (
                    <p className="mt-0.5 text-xs text-zinc-500">{e.why_they_fit[0]}</p>
                  )}
                  {e.recruiter_decision && (
                    <p className="mt-0.5 text-xs text-zinc-500">recruiter: {e.recruiter_decision}</p>
                  )}
                </div>
                {e.tier ? (
                  <StatusChip label={`Tier ${e.tier}`} variant={tierVariant(e.tier)} />
                ) : (
                  <StatusChip label="Not prioritized" variant="pending" />
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
